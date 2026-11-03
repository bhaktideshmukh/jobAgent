import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext

from src.config import BROWSER_USER_DATA_DIR, LOGS_DIR, get_resume_path, get_cover_letter_path
from src.rag_engine import ProfileRAG

SCREENSHOTS_DIR = LOGS_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

class JobApplicationBrowser:
    """
    Automates opening job links, interacting with Easy Apply modals,
    autofills fields via RAG, uploads resumes, and submits applications.
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.rag = ProfileRAG()
        self.playwright = None
        self.context: Optional[BrowserContext] = None

    def start(self):
        """Initializes persistent browser context."""
        BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_USER_DATA_DIR),
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
            ],
            viewport=None
        )

    def close(self):
        """Closes browser context."""
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    def _get_modal(self, page: Page):
        """Finds the active Easy Apply modal element by inspecting visible dialogs."""
        candidates = page.locator("div.artdeco-modal, div.jobs-easy-apply-modal, div[role='dialog']").all()
        for c in candidates:
            try:
                if c.is_visible():
                    if c.locator("button[aria-label*='Dismiss'], button:has-text('Next'), button:has-text('Review'), button:has-text('Submit')").count() > 0:
                        return c
            except Exception:
                continue
        for c in candidates:
            if c.is_visible():
                return c
        return page.locator("div[role='dialog']").first

    def _get_input_label(self, modal, inp) -> str:
        """Finds the label or prompt question for an input element."""
        # 1. aria-label
        aria = inp.get_attribute("aria-label")
        if aria and aria.strip():
            return aria.strip()

        # 2. id -> XPath label search (handles colons safely)
        inp_id = inp.get_attribute("id")
        if inp_id:
            try:
                lbl = modal.locator(f"xpath=//label[@for='{inp_id}']")
                if lbl.count() > 0 and lbl.first.is_visible():
                    return lbl.first.inner_text().strip()
            except Exception:
                pass

        # 3. Label inside closest parent container
        try:
            parent = inp.locator("xpath=ancestor::div[contains(@class, 'form') or contains(@class, 'fb-') or contains(@class, 'component')][1]")
            if parent.count() > 0:
                lbl = parent.locator("label").first
                if lbl.count() > 0 and lbl.is_visible():
                    return lbl.inner_text().strip()
                txt = parent.inner_text().split("\n")[0].strip()
                if txt:
                    return txt
        except Exception:
            pass

        return ""

    def _fill_text_inputs(self, modal):
        """Fills visible text, number, tel inputs, and textareas, scrolling when needed."""
        inputs = modal.locator("input[type='text'], input[type='tel'], input[type='number'], textarea").all()
        for inp in inputs:
            try:
                # Scroll element into view inside the modal dialog
                try:
                    inp.scroll_into_view_if_needed(timeout=2000)
                    time.sleep(0.1)
                except Exception:
                    pass

                if not inp.is_visible():
                    continue

                current_val = inp.input_value().strip()
                question = self._get_input_label(modal, inp)
                if not question:
                    question = "Field"

                # If current input is empty or marked as invalid, fill it
                if not current_val or current_val == "Invalid input":
                    answer = self.rag.answer_screening_question(question)
                    print(f"    [Input] '{question}' -> Filling: '{answer}'")
                    inp.click()
                    inp.fill("")
                    inp.fill(answer)
                    time.sleep(0.2)
            except Exception as e:
                print(f"    [Input Error] {e}")

    def _fill_select_dropdowns(self, modal):
        """Handles <select> dropdowns in the modal."""
        selects = modal.locator("select").all()
        for sel in selects:
            try:
                try:
                    sel.scroll_into_view_if_needed(timeout=2000)
                    time.sleep(0.1)
                except Exception:
                    pass

                if not sel.is_visible():
                    continue

                question = self._get_input_label(modal, sel) or "Dropdown"
                answer = self.rag.answer_screening_question(question).lower()

                options = sel.locator("option").all()
                best_option_val = None
                for opt in options:
                    opt_text = opt.inner_text().strip().lower()
                    opt_val = opt.get_attribute("value")
                    if answer in opt_text or (answer == "yes" and "yes" in opt_text) or (answer == "no" and "no" in opt_text):
                        best_option_val = opt_val
                        break

                if best_option_val is not None:
                    print(f"    [Select] '{question}' -> Selected: '{best_option_val}'")
                    sel.select_option(value=best_option_val)
                    time.sleep(0.2)
            except Exception as e:
                print(f"    [Select Error] {e}")

    def _fill_radio_buttons(self, modal):
        """Handles Yes/No and multiple-choice radio fieldsets."""
        fieldsets = modal.locator("fieldset").all()
        for fs in fieldsets:
            try:
                try:
                    fs.scroll_into_view_if_needed(timeout=2000)
                    time.sleep(0.1)
                except Exception:
                    pass

                legend = fs.locator("legend").inner_text().strip()
                if not legend:
                    continue
                answer = self.rag.answer_screening_question(legend).lower()

                radios = fs.locator("input[type='radio']").all()
                for radio in radios:
                    radio_id = radio.get_attribute("id")
                    radio_label = ""
                    if radio_id:
                        lbl = fs.locator(f"xpath=//label[@for='{radio_id}']")
                        if lbl.count() > 0:
                            radio_label = lbl.first.inner_text().strip().lower()

                    if answer in radio_label or (answer == "yes" and "yes" in radio_label) or (answer == "no" and "no" in radio_label):
                        if not radio.is_checked():
                            print(f"    [Radio] '{legend}' -> Checking: '{radio_label}'")
                            radio.check(force=True)
                            time.sleep(0.2)
                        break
            except Exception as e:
                print(f"    [Radio Error] {e}")

    def _handle_file_uploads(self, modal):
        """Uploads candidate resume if file input is present."""
        resume_path = get_resume_path()
        file_inputs = modal.locator("input[type='file']").all()

        for finp in file_inputs:
            try:
                if resume_path.exists():
                    print(f"    [Upload] Attaching resume: {resume_path.name}")
                    finp.set_input_files(str(resume_path))
                    time.sleep(1)
            except Exception as e:
                print(f"    [Upload Error] {e}")

    def process_application(self, job_url: str, auto_submit: bool = True) -> Dict[str, Any]:
        """
        Navigates to job URL, detects Easy Apply, steps through the modal,
        autofills fields, attaches files, and submits the application.
        """
        if not self.context:
            self.start()

        page = self.context.new_page()
        result = {
            "job_url": job_url,
            "easy_apply_found": False,
            "status": "failed",
            "screenshot_path": None,
            "error": None
        }

        try:
            print(f"Opening: {job_url}")
            page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            # Check if role is already applied
            already_applied = page.locator("span.artdeco-inline-feedback:has-text('Applied'), button:has-text('Applied')").first
            if already_applied.count() > 0 and already_applied.is_visible():
                print("Notice: You have already applied to this role on LinkedIn!")
                result["status"] = "already_applied"
                page.close()
                return result

            # Look for Easy Apply button
            easy_apply_btn = page.locator("button.jobs-apply-button, button:has-text('Easy Apply'), button[aria-label*='Easy Apply']").first
            
            if not easy_apply_btn.is_visible(timeout=5000):
                result["error"] = "No Easy Apply button visible (may require login or external redirect)"
                page.screenshot(path=str(SCREENSHOTS_DIR / "no_easy_apply_found.png"))
                page.close()
                return result

            result["easy_apply_found"] = True
            print("Found Easy Apply button! Clicking...")
            easy_apply_btn.click()
            time.sleep(2.5)

            # Wait for modal animation
            try:
                page.locator("button:has-text('Next'), button[aria-label*='Dismiss'], div.artdeco-modal").first.wait_for(state="visible", timeout=6000)
            except Exception:
                pass

            modal = self._get_modal(page)
            print("Easy Apply modal successfully detected!")

            # Step through application wizard modal
            max_steps = 10
            for step in range(1, max_steps + 1):
                print(f"\n--- [Application Step {step}] ---")
                
                # Fill inputs on current view
                self._fill_text_inputs(modal)
                self._fill_select_dropdowns(modal)
                self._fill_radio_buttons(modal)
                self._handle_file_uploads(modal)
                time.sleep(1)

                # Capture step screenshot
                step_img = SCREENSHOTS_DIR / f"step_{step}.png"
                page.screenshot(path=str(step_img))

                # Check for Submit / Review / Next buttons
                submit_btn = page.locator("div.artdeco-modal button:has-text('Submit application'), button[aria-label*='Submit application'], button:has-text('Submit application')").first
                review_btn = page.locator("div.artdeco-modal button:has-text('Review'), button[aria-label*='Review your application'], button:has-text('Review')").first
                next_btn = page.locator("div.artdeco-modal button:has-text('Next'), button[aria-label*='Continue to next step'], button:has-text('Next')").first

                if submit_btn.count() > 0 and submit_btn.is_visible():
                    print("Reached final step! 'Submit application' button is visible.")
                    review_file = SCREENSHOTS_DIR / f"before_submit_{int(time.time())}.png"
                    page.screenshot(path=str(review_file))
                    
                    if auto_submit:
                        print("Clicking 'Submit application'...")
                        submit_btn.click()
                        time.sleep(3)
                        # Check for confirmation
                        confirm_file = SCREENSHOTS_DIR / f"submitted_{int(time.time())}.png"
                        page.screenshot(path=str(confirm_file))
                        result["status"] = "submitted"
                        result["screenshot_path"] = str(confirm_file)
                        print("Application successfully submitted on LinkedIn!")
                    else:
                        result["status"] = "ready_for_review"
                        result["screenshot_path"] = str(review_file)
                    break

                if review_btn.count() > 0 and review_btn.is_visible():
                    print("Found 'Review' button! Clicking to enter review page...")
                    review_btn.click()
                    time.sleep(2)
                    continue

                if next_btn.count() > 0 and next_btn.is_visible():
                    print("Found 'Next' button! Advancing to next step...")
                    next_btn.click()
                    time.sleep(2)
                    
                    # Check if there are validation errors blocking progress
                    errors = page.locator(".artdeco-inline-feedback--error, [data-test-form-element-error-messages]").all()
                    if errors:
                        err_texts = [e.inner_text().strip() for e in errors if e.is_visible()]
                        if err_texts:
                            print(f"  [Validation Notice] {err_texts}")
                    continue

                print(f"No Next/Review/Submit buttons visible on step {step}. Halting wizard.")
                break

            print("\nWaiting 4 seconds before closing browser...")
            time.sleep(4)
            page.close()
            return result

        except Exception as e:
            result["error"] = str(e)
            print(f"Error during application process: {e}")
            try:
                page.screenshot(path=str(SCREENSHOTS_DIR / "error_snapshot.png"))
                page.close()
            except Exception:
                pass
            return result
