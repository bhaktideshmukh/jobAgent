import os
import re
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Set
from playwright.sync_api import sync_playwright, Page, BrowserContext

from src.config import BROWSER_USER_DATA_DIR, LOGS_DIR, get_resume_path, get_cover_letter_path
from src.rag_engine import ProfileRAG

SCREENSHOTS_DIR = LOGS_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

class JobApplicationBrowser:
    """
    Automates opening job links, interacting with Easy Apply modals (LinkedIn & Indeed),
    autofills fields via RAG, uploads resumes & cover letters, and submits applications.
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

    def _is_field_required(self, container, element) -> bool:
        """
        Determines if a form field is required (has an asterisk '*' or required attribute).
        Skips optional fields, while ensuring mandatory screening questions are filled.
        """
        try:
            elem_id = element.get_attribute("id") or ""
            aria = (element.get_attribute("aria-label") or "").lower()
            name = (element.get_attribute("name") or "").lower()
            desc = f"{elem_id} {name} {aria}".lower()

            # Rule: Keep middle name empty
            if any(k in desc for k in ["middle name", "middlename"]):
                return False

            # Explicitly marked optional in aria
            if "(optional)" in aria or "optional" in aria:
                return False

            # Check label for (optional)
            if elem_id:
                lbl = container.locator(f"xpath=//label[@for='{elem_id}']")
                if lbl.count() > 0:
                    lbl_text = lbl.first.inner_text().lower()
                    if "(optional)" in lbl_text or "optional" in lbl_text:
                        return False
                    if "*" in lbl_text or "(required)" in lbl_text or "required" in lbl_text:
                        return True

            # Check HTML5 and ARIA required attributes
            if element.get_attribute("required") is not None:
                return True
            if element.get_attribute("aria-required") == "true":
                return True

            if "*" in aria or "(required)" in aria or "required" in aria:
                return True

            # Check parent wrapper / form group
            try:
                parent = element.locator("xpath=ancestor::div[contains(@class, 'form') or contains(@class, 'fb-') or contains(@class, 'component') or contains(@class, 'ia-') or contains(@class, 'artdeco-')][1]")
                if parent.count() > 0:
                    parent_text = parent.inner_text().lower()
                    parent_html = parent.evaluate("el => el.innerHTML").lower()
                    
                    if "(optional)" in parent_text or "(optional)" in parent_html:
                        return False
                        
                    if "*" in parent_text or "(required)" in parent_text or "required" in parent_html or "asterisk" in parent_html or "is-required" in parent_html:
                        return True
            except Exception:
                pass

            # Check label prompt question
            label_text = self._get_input_label(container, element).lower()
            if "(optional)" in label_text:
                return False
            if "*" in label_text or "required" in label_text:
                return True

            # Screening topics in application forms are required by default unless marked optional
            mandatory_screening_topics = [
                "experience", "years", "ctc", "salary", "notice", "join", "commute",
                "hybrid", "onsite", "wfo", "eligible", "authorized", "visa", "sponsorship",
                "rate yourself", "proficiency", "worked with", "worked on", "requirement",
                "qualification", "jd", "job description"
            ]
            if any(t in label_text for t in mandatory_screening_topics):
                return True

        except Exception:
            pass

        return False

    def _fill_text_inputs(self, container, filled_ids: Set[str]):
        """Fills visible text, number, tel inputs, and textareas smoothly without flickering."""
        inputs = container.locator("input[type='text'], input[type='tel'], input[type='number'], textarea").all()
        for inp in inputs:
            try:
                if not inp.is_visible():
                    continue

                inp_id = inp.get_attribute("id") or ""
                inp_name = inp.get_attribute("name") or ""
                inp_aria = inp.get_attribute("aria-label") or ""
                field_key = f"{inp_id}_{inp_name}_{inp_aria}".strip("_")

                question = self._get_input_label(container, inp) or "Field"
                desc = f"{inp_id} {inp_name} {inp_aria} {question}".lower()

                # User Rule: Keep 'middle name' field empty
                if any(k in desc for k in ["middle name", "middlename", "middle initial"]):
                    if field_key:
                        filled_ids.add(field_key)
                    print(f"    [Input] Skipping 'middle name' field (kept empty per rule)")
                    continue

                # User Rule: Only fill fields that have an asterisk '*' or are required
                if not self._is_field_required(container, inp):
                    current_val = inp.input_value().strip()
                    if current_val:
                        if field_key:
                            filled_ids.add(field_key)
                    print(f"    [Input] Skipping optional field without asterisk: '{question}'")
                    continue

                current_val = inp.input_value().strip()

                # If already filled with valid input, skip without touching to prevent focus theft & flickering
                if current_val and current_val != "Invalid input":
                    if field_key:
                        filled_ids.add(field_key)
                    continue

                if field_key and field_key in filled_ids:
                    continue

                tag_type = inp.get_attribute("type") or "text"
                is_number = (tag_type == "number") or any(w in question.lower() for w in ["how many", "years", "number of", "days", "rating", "scale", "yoe"])
                answer = self.rag.answer_screening_question(question, input_type="number" if is_number else "text")
                print(f"    [Input] '{question}' -> Filling: '{answer}'")

                # Clean fill: sets value smoothly and dispatches events
                inp.fill(str(answer))
                try:
                    inp.dispatch_event("input")
                    inp.dispatch_event("change")
                except Exception:
                    pass

                if field_key:
                    filled_ids.add(field_key)
                time.sleep(0.15)
            except Exception as e:
                print(f"    [Input Error] {e}")

    def _select_best_option(self, sel, question: str, answer: str) -> bool:
        """Selects the best matching option in a <select> element, prioritizing highest ratings."""
        try:
            options = sel.locator("option").all()
            if not options:
                return False

            q_lower = question.lower()
            ans_lower = answer.lower()
            is_rating = any(term in q_lower for term in ["rate yourself", "rate your", "rating", "scale of", "proficiency"])

            opt_data = []
            for opt in options:
                text = opt.inner_text().strip()
                val = opt.get_attribute("value") or ""
                opt_data.append((opt, text, val))

            # 1. Rating questions -> select highest numeric value or Expert
            if is_rating:
                numeric_opts = []
                for opt, text, val in opt_data:
                    nums = re.findall(r'\b\d+\b', text) or re.findall(r'\b\d+\b', val)
                    if nums:
                        numeric_opts.append((int(nums[0]), val))
                if numeric_opts:
                    highest_val = max(numeric_opts, key=lambda x: x[0])[1]
                    sel.select_option(value=highest_val)
                    print(f"    [Select Rating] '{question}' -> Selected highest: '{highest_val}'")
                    return True

                for opt, text, val in opt_data:
                    if any(term in text.lower() for term in ["expert", "advanced", "proficient", "fluent"]):
                        sel.select_option(value=val)
                        print(f"    [Select Rating] '{question}' -> Selected: '{text}'")
                        return True

            # 2. Direct string / value match
            for opt, text, val in opt_data:
                t_lower = text.lower()
                v_lower = val.lower()
                if not text or "select" in t_lower or "choose" in t_lower:
                    continue
                if ans_lower == t_lower or ans_lower == v_lower or ans_lower in t_lower or ans_lower in v_lower:
                    sel.select_option(value=val)
                    print(f"    [Select] '{question}' -> Selected: '{text}'")
                    return True

            # 3. Semantic mappings
            if ans_lower == "yes":
                for opt, text, val in opt_data:
                    if "yes" in text.lower():
                        sel.select_option(value=val)
                        return True
            elif ans_lower == "no":
                for opt, text, val in opt_data:
                    if "no" in text.lower():
                        sel.select_option(value=val)
                        return True
            elif ans_lower == "0" or "immediate" in ans_lower:
                for opt, text, val in opt_data:
                    if any(term in text.lower() for term in ["0", "immediate", "less than", "15 days"]):
                        sel.select_option(value=val)
                        return True
            elif ans_lower == "2":
                for opt, text, val in opt_data:
                    nums = re.findall(r'\b\d+\b', text)
                    if nums and int(nums[0]) == 2:
                        sel.select_option(value=val)
                        return True
                    if any(term in text.lower() for term in ["2", "1-3", "2-3", "2+"]):
                        sel.select_option(value=val)
                        return True
            elif any(w in q_lower for w in ["country code", "calling code", "dial code", "phone code"]) or "india" in ans_lower or "+91" in ans_lower:
                for opt, text, val in opt_data:
                    if "+91" in text or "india" in text.lower() or val.lower() == "in":
                        sel.select_option(value=val)
                        print(f"    [Select Country Code] '{question}' -> Selected: '{text}'")
                        return True
            elif "bachelor" in ans_lower:
                for opt, text, val in opt_data:
                    if any(term in text.lower() for term in ["bachelor", "b.tech", "graduate", "degree"]):
                        sel.select_option(value=val)
                        return True

            # 4. Fallback for unselected required dropdown
            curr_val = sel.input_value()
            if not curr_val or curr_val in ["", "0", "-1"]:
                for opt, text, val in opt_data:
                    if val and text and not any(ph in text.lower() for ph in ["select an option", "please select", "choose", "select..."]):
                        sel.select_option(value=val)
                        print(f"    [Select Fallback] '{question}' -> Selected first valid option: '{text}'")
                        return True

            return False
        except Exception as e:
            print(f"    [Option Select Error] {e}")
            return False

    def _fill_select_dropdowns(self, container, filled_ids: Set[str]):
        """Handles standard <select> dropdowns smoothly."""
        selects = container.locator("select").all()
        for sel in selects:
            try:
                if not sel.is_visible():
                    continue

                sel_id = sel.get_attribute("id") or sel.get_attribute("name") or ""
                if sel_id and sel_id in filled_ids:
                    continue

                question = self._get_input_label(container, sel) or "Dropdown"
                answer = self.rag.answer_screening_question(question)

                success = self._select_best_option(sel, question, answer)
                if success and sel_id:
                    filled_ids.add(sel_id)
                time.sleep(0.15)
            except Exception as e:
                print(f"    [Select Error] {e}")

    def _fill_custom_comboboxes(self, container, filled_ids: Set[str]):
        """Handles modern custom dropdowns, comboboxes, and typeaheads (LinkedIn & Indeed)."""
        combos = container.locator("input[role='combobox'], div[role='combobox'], button[aria-haspopup='listbox']").all()
        for combo in combos:
            try:
                if not combo.is_visible():
                    continue

                combo_id = combo.get_attribute("id") or combo.get_attribute("aria-label") or ""
                if combo_id and combo_id in filled_ids:
                    continue

                question = self._get_input_label(container, combo) or "Combobox"
                desc = f"{combo_id} {question}".lower()

                # User Rule: Keep 'middle name' field empty
                if any(k in desc for k in ["middle name", "middlename", "middle initial"]):
                    if combo_id:
                        filled_ids.add(combo_id)
                    print(f"    [Combobox] Skipping 'middle name' field (kept empty per rule)")
                    continue

                # User Rule: Only fill fields that have an asterisk '*' or are required
                if not self._is_field_required(container, combo):
                    if combo_id:
                        filled_ids.add(combo_id)
                    print(f"    [Combobox] Skipping optional field without asterisk: '{question}'")
                    continue

                answer = self.rag.answer_screening_question(question)
                is_rating = any(term in question.lower() for term in ["rate yourself", "rate your", "rating", "scale of", "proficiency"])

                tag = combo.evaluate("el => el.tagName.toLowerCase()")
                
                # 1. Combobox text input (e.g. LinkedIn autocomplete fields)
                if tag == "input":
                    current_val = combo.input_value().strip()
                    if current_val and current_val != "Invalid input":
                        if combo_id:
                            filled_ids.add(combo_id)
                        continue

                    print(f"    [Combobox Input] '{question}' -> Filling: '{answer}'")
                    combo.fill(str(answer))
                    time.sleep(0.3)

                    # Look for autocomplete popup options
                    popup_options = container.locator("div[role='listbox'] div[role='option'], ul[role='listbox'] li, .artdeco-typeahead__result-item").all()
                    if popup_options:
                        clicked = False
                        for pop in popup_options:
                            if answer.lower() in pop.inner_text().strip().lower():
                                pop.click()
                                clicked = True
                                break
                        if not clicked and popup_options[0].is_visible():
                            popup_options[0].click()
                    else:
                        combo.press("Enter")
                    
                    if combo_id:
                        filled_ids.add(combo_id)
                    time.sleep(0.2)

                # 2. Custom button dropdowns (e.g. Indeed / React select buttons)
                elif tag in ["button", "div"]:
                    current_text = combo.inner_text().strip()
                    if current_text and not any(ph in current_text.lower() for ph in ["select", "choose", "please"]):
                        if combo_id:
                            filled_ids.add(combo_id)
                        continue

                    print(f"    [Custom Dropdown] Opening '{question}'...")
                    combo.click()
                    time.sleep(0.4)

                    options = container.locator("div[role='option'], li[role='option'], [role='menuitem']").all()
                    if not options:
                        options = container.page.locator("div[role='option'], li[role='option'], div.artdeco-dropdown__item").all()

                    if options:
                        chosen = None
                        if is_rating:
                            num_opts = []
                            for opt in options:
                                txt = opt.inner_text().strip()
                                nums = re.findall(r'\b\d+\b', txt)
                                if nums:
                                    num_opts.append((int(nums[0]), opt))
                            if num_opts:
                                chosen = max(num_opts, key=lambda x: x[0])[1]
                            else:
                                for opt in options:
                                    if any(t in opt.inner_text().lower() for t in ["expert", "advanced"]):
                                        chosen = opt
                                        break
                        if not chosen:
                            for opt in options:
                                txt = opt.inner_text().strip().lower()
                                if answer.lower() in txt or (answer.lower() == "yes" and "yes" in txt) or (answer.lower() == "no" and "no" in txt):
                                    chosen = opt
                                    break
                                if answer == "0" and any(k in txt for k in ["0", "immediate", "less than", "15 days"]):
                                    chosen = opt
                                    break
                                if answer == "2" and any(k in txt for k in ["2", "1-3", "2-3", "2+"]):
                                    chosen = opt
                                    break
                        if not chosen and options:
                            chosen = options[0]

                        if chosen:
                            print(f"    [Custom Dropdown] Selecting option: '{chosen.inner_text().strip()}'")
                            chosen.click()
                            time.sleep(0.2)

                    if combo_id:
                        filled_ids.add(combo_id)
            except Exception as e:
                print(f"    [Custom Dropdown Error] {e}")

    def _fill_radio_buttons(self, container, filled_ids: Set[str]):
        """Handles Yes/No, rating, and multiple-choice radio fieldsets smoothly."""
        fieldsets = container.locator("fieldset").all()
        for fs in fieldsets:
            try:
                if not fs.is_visible():
                    continue

                legend_loc = fs.locator("legend")
                if legend_loc.count() == 0:
                    continue
                legend = legend_loc.inner_text().strip()
                if not legend or legend in filled_ids:
                    continue

                radios = fs.locator("input[type='radio']").all()
                if not radios:
                    continue

                # If already selected, skip
                if any(r.is_checked() for r in radios):
                    filled_ids.add(legend)
                    continue

                answer = self.rag.answer_screening_question(legend).lower()
                is_rating = any(term in legend.lower() for term in ["rate yourself", "rate your", "rating", "scale of", "proficiency"])

                # Rating fieldset -> check the highest numeric radio
                if is_rating:
                    best_radio = None
                    max_val = -1
                    for r in radios:
                        lbl = self._get_input_label(fs, r)
                        nums = re.findall(r'\b\d+\b', lbl)
                        if nums:
                            val = int(nums[0])
                            if val > max_val:
                                max_val = val
                                best_radio = r
                    if best_radio:
                        print(f"    [Radio Rating] '{legend}' -> Checking highest: {max_val}")
                        best_radio.check(force=True)
                        filled_ids.add(legend)
                        time.sleep(0.15)
                        continue

                # Standard matching
                for radio in radios:
                    radio_label = self._get_input_label(fs, radio).lower()
                    if answer in radio_label or (answer == "yes" and "yes" in radio_label) or (answer == "no" and "no" in radio_label):
                        print(f"    [Radio] '{legend}' -> Checking: '{radio_label}'")
                        radio.check(force=True)
                        filled_ids.add(legend)
                        time.sleep(0.15)
                        break
                    if answer == "0" and any(k in radio_label for k in ["0", "immediate", "less than", "15 days"]):
                        print(f"    [Radio Joining] '{legend}' -> Checking: '{radio_label}'")
                        radio.check(force=True)
                        filled_ids.add(legend)
                        time.sleep(0.15)
                        break
                    if answer == "2" and any(k in radio_label for k in ["2", "1-3", "2-3", "2+"]):
                        print(f"    [Radio YOE] '{legend}' -> Checking: '{radio_label}'")
                        radio.check(force=True)
                        filled_ids.add(legend)
                        time.sleep(0.15)
                        break
            except Exception as e:
                print(f"    [Radio Error] {e}")

    def _handle_file_uploads(self, container):
        """
        Uploads candidate resume if file input is present.
        Cover letter uploading is disabled per user preference.
        """
        resume_path = get_resume_path()
        file_inputs = container.locator("input[type='file']").all()

        for finp in file_inputs:
            try:
                finp_id = finp.get_attribute("id") or ""
                finp_name = finp.get_attribute("name") or ""
                finp_aria = finp.get_attribute("aria-label") or ""
                lbl = self._get_input_label(container, finp)
                desc = f"{finp_id} {finp_name} {finp_aria} {lbl}".lower()

                # Skip any inputs specifically asking for a cover letter
                if any(k in desc for k in ["cover", "letter", "coverletter"]):
                    print(f"    [Upload] Skipping cover letter input (disabled per preference)")
                    continue

                if resume_path.exists():
                    print(f"    [Upload] Attaching Resume: {resume_path.name}")
                    finp.set_input_files(str(resume_path))
                    time.sleep(0.5)
            except Exception as e:
                print(f"    [Upload Error] {e}")

    def _fill_consent_checkboxes(self, container, page: Page, filled_ids: Set[str] = None):
        """
        Detects and ticks required consent, agreements, technology/skills, commute,
        hybrid/onsite, and qualification checkboxes.
        Strictly ignores and unchecks the 'Follow company' checkbox.
        """
        try:
            # 1. Primary Strategy: In-page DOM evaluation to locate & click checkboxes/labels
            page.evaluate("""() => {
                const inputs = Array.from(document.querySelectorAll("input[type='checkbox']"));
                for (const inp of inputs) {
                    const id = (inp.id || "").toLowerCase();
                    const name = (inp.name || "").toLowerCase();
                    const label = document.querySelector(`label[for='${inp.id}']`) || inp.closest("label");
                    const labelText = label ? label.innerText.toLowerCase() : "";
                    const parentText = inp.parentElement ? inp.parentElement.innerText.toLowerCase() : "";
                    const fullDesc = (id + " " + name + " " + labelText + " " + parentText).toLowerCase();

                    // Never tick the "Follow company" or negative exclusion checkboxes
                    const isExcluded = fullDesc.includes("follow") || id.includes("follow") || name.includes("follow") ||
                                       fullDesc.includes("stay up to date") ||
                                       fullDesc.includes("previously worked") || fullDesc.includes("former employee") ||
                                       fullDesc.includes("sponsorship") || fullDesc.includes("serving notice") ||
                                       fullDesc.includes("serving np") || fullDesc.includes("decline") ||
                                       fullDesc.includes("opt out");
                    if (isExcluded) continue;

                    const isConsent = fullDesc.includes("consent") || 
                                     fullDesc.includes("agree") || 
                                     fullDesc.includes("terms") || 
                                     fullDesc.includes("privacy") || 
                                     fullDesc.includes("certify") || 
                                     fullDesc.includes("acknowledge") ||
                                     fullDesc.includes("declare") ||
                                     fullDesc.includes("truthful");

                    const isRequired = inp.required || 
                                       inp.getAttribute("aria-required") === "true" ||
                                       fullDesc.includes("required") ||
                                       fullDesc.includes("*");

                    const isTechOrSkill = fullDesc.includes("python") || fullDesc.includes("aws") || fullDesc.includes("docker") ||
                                          fullDesc.includes("kubernetes") || fullDesc.includes("sql") || fullDesc.includes("react") ||
                                          fullDesc.includes("java") || fullDesc.includes("c#") || fullDesc.includes("git") ||
                                          fullDesc.includes("devops") || fullDesc.includes("ci/cd") || fullDesc.includes("experience") ||
                                          fullDesc.includes("skill") || fullDesc.includes("technology") || fullDesc.includes("technologies") ||
                                          fullDesc.includes("worked with") || fullDesc.includes("worked on");

                    const isEligibility = fullDesc.includes("commute") || fullDesc.includes("hybrid") || fullDesc.includes("onsite") ||
                                          fullDesc.includes("wfo") || fullDesc.includes("eligible") || fullDesc.includes("requirements") ||
                                          fullDesc.includes("qualifications") || fullDesc.includes("jd") || fullDesc.includes("authorized");

                    const inQuestionGroup = inp.closest("fieldset, .jobs-easy-apply-form-section__grouping, .fb-form-element, [data-test-form-element], .ia-Questions-item") !== null;

                    if (isConsent || isRequired || isTechOrSkill || isEligibility || inQuestionGroup) {
                        if (!inp.checked) {
                            if (label) {
                                label.click();
                            } else {
                                inp.click();
                            }
                            inp.checked = true;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }
                }

                // Check for standalone visible labels with text like 'I consent' or 'I agree'
                const labels = Array.from(document.querySelectorAll("label, span.artdeco-checkbox__label"));
                for (const lbl of labels) {
                    const txt = (lbl.innerText || "").toLowerCase().trim();
                    if (txt.includes("follow") || txt.includes("previously worked") || txt.includes("sponsorship")) continue;
                    
                    if (txt === "i consent" || txt === "i agree" || txt.startsWith("i consent") || txt.startsWith("i agree") || txt.includes("consent") || txt.includes("terms and conditions")) {
                        const parent = lbl.closest(".artdeco-checkbox") || lbl.closest("label") || lbl;
                        const input = parent.querySelector("input[type='checkbox']") || 
                                      (lbl.htmlFor ? document.querySelector(`#${lbl.htmlFor}`) : null);
                        if (!input || !input.checked) {
                            lbl.click();
                            if (input) {
                                input.checked = true;
                                input.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        }
                    }
                }
            }""")
            time.sleep(0.2)

            # 2. Secondary Strategy: Playwright locators for labels containing "I consent", "consent", "I agree"
            consent_label_selectors = [
                "label:has-text('I consent')",
                "label:has-text('consent')",
                "label:has-text('I agree')",
                "label:has-text('agree to')",
                "span.artdeco-checkbox__label:has-text('consent')",
                "span.artdeco-checkbox__label:has-text('agree')"
            ]
            for scope in [container, page]:
                for sel in consent_label_selectors:
                    try:
                        labels = scope.locator(sel).all()
                        for lbl in labels:
                            if not lbl.is_visible():
                                continue
                            txt = lbl.inner_text().lower().strip()
                            if "follow" in txt or "previously worked" in txt or "sponsorship" in txt:
                                continue
                            
                            for_id = lbl.get_attribute("for")
                            is_checked = False
                            if for_id:
                                inp = scope.locator(f"#{for_id}").first
                                if inp.count() > 0:
                                    is_checked = inp.is_checked()
                            else:
                                inp = lbl.locator("input[type='checkbox']").first
                                if inp.count() > 0:
                                    is_checked = inp.is_checked()

                            if not is_checked:
                                print(f"    [Checkbox Consent] Clicking consent label: '{lbl.inner_text().strip()[:50]}'")
                                lbl.click(force=True)
                                time.sleep(0.2)
                    except Exception:
                        continue

            # 3. Direct check on all input[type='checkbox'] elements (with force=True even if hidden)
            for scope in [container, page]:
                try:
                    cbs = scope.locator("input[type='checkbox']").all()
                    for cb in cbs:
                        try:
                            cb_id = cb.get_attribute("id") or ""
                            desc = (cb_id + " " + (cb.get_attribute("name") or "") + " " + (cb.get_attribute("aria-label") or "")).lower()
                            if "follow" in desc or cb_id == "follow-company-checkbox" or any(ex in desc for ex in ["previously worked", "former employee", "sponsorship", "serving notice", "decline", "opt out"]):
                                continue
                            if not cb.is_checked():
                                print(f"    [Checkbox] Force checking input: #{cb_id}")
                                cb.check(force=True)
                                time.sleep(0.15)
                        except Exception:
                            continue
                except Exception:
                    pass

            # Final check: always ensure follow company checkbox remains unchecked
            self._uncheck_follow_company(container, page)

        except Exception as e:
            print(f"    [Consent Checkboxes Error] {e}")

    def _uncheck_follow_company(self, container, page: Page) -> bool:
        """
        Unchecks the 'Follow company' checkbox on LinkedIn before submitting.
        Simulates a real click on the visible label/indicator so LinkedIn's React/Ember state updates.
        """
        try:
            # 1. Primary Strategy: Evaluate in browser context and trigger label.click()
            result = page.evaluate("""() => {
                const cb = document.querySelector("#follow-company-checkbox") || 
                           Array.from(document.querySelectorAll("input[type='checkbox']")).find(i => {
                               const desc = (i.id + ' ' + i.name + ' ' + (i.parentElement ? i.parentElement.innerText : '')).toLowerCase();
                               return desc.includes('follow') || desc.includes('stay up to date');
                           });

                const label = document.querySelector("label[for='follow-company-checkbox']") || 
                              Array.from(document.querySelectorAll("label, span, div.artdeco-checkbox")).find(l => {
                                  const txt = (l.innerText || "").toLowerCase();
                                  return txt.includes('stay up to date') || (txt.includes('follow') && txt.includes('page'));
                              });

                let unchecked = false;

                if (cb) {
                    const isChecked = cb.checked || cb.getAttribute('checked') !== null || cb.getAttribute('aria-checked') === 'true';
                    if (isChecked) {
                        if (label) {
                            label.click();
                        } else {
                            cb.click();
                        }
                        cb.checked = false;
                        cb.removeAttribute('checked');
                        cb.setAttribute('aria-checked', 'false');
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                        cb.dispatchEvent(new Event('input', { bubbles: true }));
                        unchecked = true;
                    }
                } else if (label) {
                    label.click();
                    unchecked = true;
                }

                return {
                    unchecked: unchecked,
                    cb_found: !!cb,
                    label_found: !!label
                };
            }""")

            if isinstance(result, dict) and result.get("unchecked"):
                print(f"    [LinkedIn] Successfully unchecked 'Follow company': {result}")
                time.sleep(0.3)
                return True

            # 2. Secondary Strategy: Direct Playwright click on visible label
            label_locators = [
                "label[for='follow-company-checkbox']",
                "label:has-text('stay up to date')",
                "label:has-text('Follow ')",
                "div.jobs-easy-apply-footer__follow-company label",
                "span:has-text('stay up to date')"
            ]
            for scope in [container, page]:
                for sel in label_locators:
                    try:
                        loc = scope.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            input_el = scope.locator("input#follow-company-checkbox, input[id*='follow']").first
                            if input_el.count() > 0 and input_el.is_checked():
                                print(f"    [LinkedIn] Clicking follow label via Playwright: '{sel}'")
                                loc.click(force=True)
                                time.sleep(0.3)
                                return True
                    except Exception:
                        continue

        except Exception as e:
            print(f"    [Uncheck Follow Error] {e}")
        return False

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

            # Track filled fields per session to avoid flickering and focus stealing
            filled_ids: Set[str] = set()

            # Step through application wizard
            max_steps = 10
            for step in range(1, max_steps + 1):
                print(f"\n--- [{platform_name} Step {step}] ---")
                
                # Smooth filling without focus jumps or screen flicker
                self._fill_text_inputs(container, filled_ids)
                self._fill_select_dropdowns(container, filled_ids)
                self._fill_custom_comboboxes(container, filled_ids)
                self._fill_radio_buttons(container, filled_ids)
                self._fill_consent_checkboxes(container, apply_page, filled_ids)
                self._handle_file_uploads(container)
                self._uncheck_follow_company(container, apply_page)
                time.sleep(0.8)

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
                    # Ensure any final consent / agreement checkbox is ticked
                    self._fill_consent_checkboxes(container, apply_page, filled_ids)
                    # Always uncheck the 'Follow company' checkbox before submitting
                    self._uncheck_follow_company(container, apply_page)
                    time.sleep(0.3)
                    
                    review_file = SCREENSHOTS_DIR / f"{platform_name.lower()}_before_submit_{int(time.time())}.png"
                    apply_page.screenshot(path=str(review_file))
                    
                    if auto_submit:
                        self._uncheck_follow_company(container, apply_page)
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
