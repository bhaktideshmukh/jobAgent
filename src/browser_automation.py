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
    Automates opening job links, interacting with Easy Apply modals (LinkedIn & Indeed),
    autofills fields via RAG, uploads resumes, and submits applications.
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.rag = ProfileRAG()
        self.playwright = None
        self.context: Optional[BrowserContext] = None

    def start(self):
        """Initializes persistent browser context with stealth options."""
        BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            "--no-sandbox"
        ]

        # Prefer real Chrome if available to bypass Cloudflare/Indeed bot protections
        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_USER_DATA_DIR),
                channel="chrome",
                headless=self.headless,
                args=launch_args,
                viewport=None
            )
        except Exception:
            # Fallback to standard Chromium
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_USER_DATA_DIR),
                headless=self.headless,
                args=launch_args,
                viewport=None
            )

        # Remove webdriver flag
        self.context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def close(self):
        """Closes browser context."""
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    def _get_active_container(self, page: Page):
        """
        Finds the active application container.
        Supports LinkedIn modals, Indeed modals, and Indeed iframes.
        """
        # 1. Check for Indeed iframe
        iframes = page.locator("iframe#ia-iframe, iframe[title*='apply'], iframe[id*='apply']").all()
        for ifr in iframes:
            try:
                if ifr.is_visible():
                    return page.frame_locator(f"iframe#{ifr.get_attribute('id') or 'ia-iframe'}")
            except Exception:
                pass

        # 2. Check for dialogs (LinkedIn artdeco-modal or Indeed modal)
        candidates = page.locator("div.artdeco-modal, div.jobs-easy-apply-modal, div[role='dialog'], div[data-testid*='modal']").all()
        for c in candidates:
            try:
                if c.is_visible():
                    if c.locator("button[aria-label*='Dismiss'], button:has-text('Next'), button:has-text('Continue'), button:has-text('Review'), button:has-text('Submit')").count() > 0:
                        return c
            except Exception:
                continue

        for c in candidates:
            if c.is_visible():
                return c

        return page

    def _get_input_label(self, container, inp) -> str:
        """Finds the label or prompt question for an input element."""
        aria = inp.get_attribute("aria-label")
        if aria and aria.strip():
            return aria.strip()

        inp_id = inp.get_attribute("id")
        if inp_id:
            try:
                lbl = container.locator(f"xpath=//label[@for='{inp_id}']")
                if lbl.count() > 0 and lbl.first.is_visible():
                    return lbl.first.inner_text().strip()
            except Exception:
                pass

        try:
            parent = inp.locator("xpath=ancestor::div[contains(@class, 'form') or contains(@class, 'fb-') or contains(@class, 'component') or contains(@class, 'ia-')][1]")
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

    def _fill_text_inputs(self, container):
        """Fills visible text, number, tel inputs, and textareas, scrolling when needed."""
        inputs = container.locator("input[type='text'], input[type='tel'], input[type='number'], textarea").all()
        for inp in inputs:
            try:
                try:
                    inp.scroll_into_view_if_needed(timeout=2000)
                    time.sleep(0.1)
                except Exception:
                    pass

                if not inp.is_visible():
                    continue

                current_val = inp.input_value().strip()
                question = self._get_input_label(container, inp)
                if not question:
                    question = "Field"

                if not current_val or current_val == "Invalid input":
                    answer = self.rag.answer_screening_question(question)
                    print(f"    [Input] '{question}' -> Filling: '{answer}'")
                    inp.click()
                    inp.fill("")
                    inp.fill(answer)
                    time.sleep(0.2)
            except Exception as e:
                print(f"    [Input Error] {e}")

    def _fill_select_dropdowns(self, container):
        """Handles <select> dropdowns in the modal/iframe."""
        selects = container.locator("select").all()
        for sel in selects:
            try:
                try:
                    sel.scroll_into_view_if_needed(timeout=2000)
                    time.sleep(0.1)
                except Exception:
                    pass

                if not sel.is_visible():
                    continue

                question = self._get_input_label(container, sel) or "Dropdown"
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

    def _fill_radio_buttons(self, container):
        """Handles Yes/No and multiple-choice radio fieldsets."""
        fieldsets = container.locator("fieldset").all()
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

    def _handle_file_uploads(self, container):
        """Uploads candidate resume if file input is present."""
        resume_path = get_resume_path()
        file_inputs = container.locator("input[type='file']").all()

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
        Navigates to job URL, detects Easy Apply / Direct Apply (LinkedIn or Indeed),
        steps through the modal/iframe, autofills fields, attaches files, and submits.
        """
        if not self.context:
            self.start()

        page = self.context.new_page()
        is_indeed = "indeed.com" in job_url.lower()
        platform_name = "Indeed" if is_indeed else "LinkedIn"

        result = {
            "job_url": job_url,
            "platform": platform_name,
            "easy_apply_found": False,
            "status": "failed",
            "screenshot_path": None,
            "error": None
        }

        try:
            print(f"Opening [{platform_name}]: {job_url}")
            page.goto(job_url, timeout=40000, wait_until="domcontentloaded")
            time.sleep(3)

            # Check for Cloudflare / Security Check
            if any(term in page.title().lower() for term in ["security check", "just a moment", "challenge"]):
                print("\n[!] Cloudflare Verification Detected in the browser window.")
                print("[!] Please complete the 'Verify you are human' checkbox on your screen...")
                for _ in range(30):
                    time.sleep(1)
                    if not any(term in page.title().lower() for term in ["security check", "just a moment", "challenge"]):
                        print("Verification passed! Waiting for job page to load...")
                        time.sleep(4)
                        break

            # Check if role is already applied
            already_applied = page.locator("span.artdeco-inline-feedback:has-text('Applied'), button:has-text('Applied'), div:has-text('You applied on Indeed'), [data-testid*='applied']").first
            if already_applied.count() > 0 and already_applied.is_visible():
                print(f"Notice: You have already applied to this role on {platform_name}!")
                result["status"] = "already_applied"
                page.close()
                return result

            # Unified Apply Button Locators
            if is_indeed:
                apply_selectors = [
                    "button:has-text('Apply now')",
                    "button:has-text('Easily apply')",
                    "#indeedApplyButton",
                    "[data-testid*='indeedApply']",
                    "button[aria-label*='Apply now']",
                    "a:has-text('Apply now')"
                ]
            else:
                apply_selectors = [
                    "button.jobs-apply-button",
                    "button:has-text('Easy Apply')",
                    "button[aria-label*='Easy Apply']"
                ]

            apply_query = ", ".join(apply_selectors)
            
            # Wait up to 15s for the button to appear after page loads
            try:
                page.wait_for_selector(apply_query, state="visible", timeout=15000)
            except Exception:
                pass

            apply_btn = page.locator(apply_query).first
            
            if not apply_btn.is_visible():
                result["error"] = f"No Direct / Easy Apply button visible on {platform_name} (may require login or external redirect)"
                page.screenshot(path=str(SCREENSHOTS_DIR / f"{platform_name.lower()}_no_apply_found.png"))
                page.close()
                return result

            result["easy_apply_found"] = True
            print(f"Found {platform_name} Apply button! Clicking...")
            
            # Click and detect if Indeed opens a popup tab or inline modal
            apply_page = page
            try:
                with page.expect_popup(timeout=4000) as popup_info:
                    apply_btn.click()
                apply_page = popup_info.value
                print("Indeed opened application in a dedicated application window.")
                apply_page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
            except Exception:
                time.sleep(3)

            container = self._get_active_container(apply_page)
            print(f"{platform_name} application container detected!")

            # Step through application wizard
            max_steps = 10
            for step in range(1, max_steps + 1):
                print(f"\n--- [{platform_name} Step {step}] ---")
                
                # Fill inputs on current view
                self._fill_text_inputs(container)
                self._fill_select_dropdowns(container)
                self._fill_radio_buttons(container)
                self._handle_file_uploads(container)
                time.sleep(1)

                # Capture step screenshot
                step_img = SCREENSHOTS_DIR / f"{platform_name.lower()}_step_{step}.png"
                apply_page.screenshot(path=str(step_img))

                # Button selectors for both platforms
                submit_selectors = [
                    "button:has-text('Submit your application')",
                    "button:has-text('Submit application')",
                    "button[aria-label*='Submit application']"
                ]
                review_selectors = [
                    "button:has-text('Review your application')",
                    "button:has-text('Review')",
                    "button[aria-label*='Review your application']"
                ]
                next_selectors = [
                    "button:has-text('Continue')",
                    "button:has-text('Next')",
                    "button[aria-label*='Continue to next step']",
                    "button[aria-label*='Continue']"
                ]

                # Wait for any of Submit, Review, or Next/Continue buttons to appear
                # (Indeed often displays a brief 2-3s 'Preparing review' loading state)
                submit_btn = None
                review_btn = None
                next_btn = None

                for wait_attempt in range(8):
                    # 1. Check for Submit
                    for sel in submit_selectors:
                        loc = apply_page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            submit_btn = loc
                            break
                    if submit_btn:
                        break

                    # 2. Check for Review
                    for sel in review_selectors:
                        loc = apply_page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            review_btn = loc
                            break
                    if review_btn:
                        break

                    # 3. Check for Next / Continue
                    for sel in next_selectors:
                        loc = apply_page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            next_btn = loc
                            break
                    if next_btn:
                        break

                    time.sleep(1)

                if submit_btn:
                    print(f"Reached final step! 'Submit' button is visible on {platform_name}.")
                    review_file = SCREENSHOTS_DIR / f"{platform_name.lower()}_before_submit_{int(time.time())}.png"
                    apply_page.screenshot(path=str(review_file))
                    
                    if auto_submit:
                        print(f"Clicking 'Submit' on {platform_name}...")
                        submit_btn.click()
                        time.sleep(3)
                        confirm_file = SCREENSHOTS_DIR / f"{platform_name.lower()}_submitted_{int(time.time())}.png"
                        apply_page.screenshot(path=str(confirm_file))
                        result["status"] = "submitted"
                        result["screenshot_path"] = str(confirm_file)
                        print(f"Application successfully submitted on {platform_name}!")
                    else:
                        result["status"] = "ready_for_review"
                        result["screenshot_path"] = str(review_file)
                    break

                if review_btn:
                    print(f"Found '{review_btn.inner_text().strip()}' button! Advancing to review page...")
                    review_btn.click()
                    time.sleep(2.5)
                    continue

                if next_btn:
                    print(f"Found '{next_btn.inner_text().strip()}' button! Advancing...")
                    next_btn.click()
                    time.sleep(2)
                    continue

                print(f"No Next/Review/Submit buttons visible on step {step}. Halting wizard.")
                break

            print("\nWaiting 4 seconds before closing browser...")
            time.sleep(4)
            try:
                if apply_page != page:
                    apply_page.close()
            except Exception:
                pass
            page.close()
            return result

        except Exception as e:
            result["error"] = str(e)
            print(f"Error during application process: {e}")
            try:
                page.screenshot(path=str(SCREENSHOTS_DIR / f"{platform_name.lower()}_error.png"))
                page.close()
            except Exception:
                pass
            return result
