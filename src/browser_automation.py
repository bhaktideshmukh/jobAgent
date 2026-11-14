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

    def _dismiss_popups_or_banners(self, page: Page):
        """Dismisses cookie banners or prompt overlays that could obstruct form buttons."""
        dismiss_selectors = [
            "#onetrust-accept-btn-handler",
            "button:has-text('Accept all cookies')",
            "button:has-text('Reject all')",
            "button:has-text('Accept')",
            "button[aria-label='Close']",
            "button.ia-DismissModal-close"
        ]
        for sel in dismiss_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    time.sleep(0.3)
            except Exception:
                pass

    def _get_active_container(self, page: Page):
        """
        Finds the active application container.
        Supports LinkedIn modals, Indeed modals, and Indeed iframes.
        """
        # Dismiss any obstructive cookie banners or popups
        self._dismiss_popups_or_banners(page)

        # 1. Check for Indeed iframe
        for sel in ["iframe#ia-iframe", "iframe[title*='apply' i]", "iframe[id*='apply' i]", "iframe[src*='indeed' i]", "iframe[src*='apply' i]"]:
            try:
                ifr = page.locator(sel).first
                if ifr.count() > 0 and ifr.is_visible():
                    return page.frame_locator(sel)
            except Exception:
                pass

        # 2. Check for dialogs (LinkedIn native HTML5 <dialog>, artdeco-modal, or Indeed modal)
        dialog_selectors = [
            "dialog",
            "dialog[open]",
            "[role='dialog']",
            "div.artdeco-modal",
            "div.jobs-easy-apply-modal",
            "div[role='dialog']",
            "div[data-testid*='modal']",
            "div.ia-BasePage",
            "#ia-container",
            "div.ia-ApplicationForm"
        ]
        for sel in dialog_selectors:
            try:
                candidates = page.locator(sel).all()
                for c in candidates:
                    if c.is_visible():
                        has_buttons = c.locator("button, input[type='submit'], [role='button']").count() > 0
                        has_inputs = c.locator("input, select, textarea").count() > 0
                        if has_buttons or has_inputs:
                            return c
            except Exception:
                continue

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

            # Essential contact fields and screening topics are mandatory unless explicitly marked optional
            mandatory_screening_topics = [
                "first name", "last name", "full name", "phone", "mobile", "email",
                "city", "postal", "zip", "location", "address", "country",
                "dob", "date of birth", "birth date", "birthdate", "birth",
                "experience", "years", "ctc", "salary", "notice", "join", "commute",
                "hybrid", "onsite", "wfo", "eligible", "authorized", "visa", "sponsorship",
                "relocate", "relocation", "willing to relocate", "4/5", "5 days", "hybrid setting", "days a week",
                "rate yourself", "proficiency", "worked with", "worked on", "requirement",
                "qualification", "jd", "job description", "education", "degree", "bachelor",
                "convicted", "criminal", "misconduct", "bankruptcy", "litigation", "hire"
            ]
            if any(t in label_text or t in desc for t in mandatory_screening_topics):
                return True

        except Exception:
            pass

        return False

    def _fill_text_inputs(self, container, filled_ids: Set[str]):
        """Fills visible text, number, tel, date inputs, and textareas smoothly without flickering."""
        inputs = container.locator("input[type='text'], input[type='tel'], input[type='number'], input[type='date'], textarea").all()
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
                input_t = "date" if tag_type == "date" else ("number" if is_number else "text")
                answer = self.rag.answer_screening_question(question, input_type=input_t)
                print(f"    [Input] '{question}' -> Filling: '{answer}'")

                # Clean fill: sets value smoothly and dispatches events
                inp.fill(str(answer))
                try:
                    inp.dispatch_event("input")
                    inp.dispatch_event("change")
                    inp.dispatch_event("blur")
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

            # 2. Education & Degree dropdowns -> strictly pick Bachelor's / Bachelors
            is_education = (
                any(w in q_lower for w in ["education", "degree", "qualification", "highest level"]) or
                "bachelor" in ans_lower or
                any("bachelor" in t.lower() or "bachelor" in v.lower() for _, t, v in opt_data) or
                (any("master" in t.lower() for _, t, v in opt_data) and any(d in t.lower() for _, t, _ in opt_data for d in ["school", "diploma", "doctor", "secondary"]))
            )
            if is_education:
                # 2a. Top Priority: Strictly match Bachelor's / Bachelors / Bachelor (normalized for apostrophes)
                for opt, text, val in opt_data:
                    t_clean = text.lower().replace("'", "").replace("’", "").strip()
                    v_clean = val.lower().replace("'", "").replace("’", "").strip()
                    if "select" in t_clean or "choose" in t_clean:
                        continue
                    if "bachelor" in t_clean or "bachelor" in v_clean:
                        sel.select_option(value=val)
                        print(f"    [Select Education] '{question}' -> Selected Bachelor's / Bachelors: '{text}' (val='{val}')")
                        return True

                # 2b. Second Priority: B.Tech, B.E, Undergraduate, 4-year degree
                for opt, text, val in opt_data:
                    t_lower = text.lower()
                    v_lower = val.lower()
                    if any(term in t_lower or term in v_lower for term in ["b.tech", "btech", "b.e", "undergraduate", "4-year"]):
                        sel.select_option(value=val)
                        print(f"    [Select Education] '{question}' -> Selected: '{text}' (val='{val}')")
                        return True

                # 2c. Third Priority: Generic Graduate / Graduation / College (excluding master/doctor/phd/associate/secondary/high school/diploma)
                for opt, text, val in opt_data:
                    t_lower = text.lower()
                    v_lower = val.lower()
                    if any(bad in t_lower or bad in v_lower for bad in ["master", "doctor", "phd", "associate", "secondary", "high school", "diploma", "intermediate"]):
                        continue
                    if any(term in t_lower or term in v_lower for term in ["graduate", "graduation", "college", "degree"]):
                        sel.select_option(value=val)
                        print(f"    [Select Education] '{question}' -> Selected: '{text}' (val='{val}')")
                        return True

            # 3. Direct string / value match
            for opt, text, val in opt_data:
                t_lower = text.lower()
                v_lower = val.lower()
                if not text or "select" in t_lower or "choose" in t_lower:
                    continue
                if ans_lower == t_lower or ans_lower == v_lower or ans_lower in t_lower or ans_lower in v_lower:
                    sel.select_option(value=val)
                    print(f"    [Select] '{question}' -> Selected: '{text}'")
                    return True

            # 4. Semantic mappings
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
            elif ans_lower in ["6", "6 months"] or (any(m in q_lower for m in ["month", "months"]) and "6" in ans_lower):
                for opt, text, val in opt_data:
                    nums = re.findall(r'\b\d+\b', text) or re.findall(r'\b\d+\b', val)
                    if nums and int(nums[0]) == 6:
                        sel.select_option(value=val)
                        print(f"    [Select Months] '{question}' -> Selected: '{text}'")
                        return True
                    if any(term in text.lower() for term in ["6 months", "6 month", "6"]):
                        sel.select_option(value=val)
                        print(f"    [Select Months] '{question}' -> Selected: '{text}'")
                        return True
            elif any(w in q_lower for w in ["country code", "calling code", "dial code", "phone code"]) or "india" in ans_lower or "+91" in ans_lower:
                for opt, text, val in opt_data:
                    if "+91" in text or "india" in text.lower() or val.lower() == "in":
                        sel.select_option(value=val)
                        print(f"    [Select Country Code] '{question}' -> Selected: '{text}'")
                        return True
            # 5. Fallback for unselected required dropdown
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
                        if "bachelor" in answer.lower():
                            for pop in popup_options:
                                p_txt = pop.inner_text().strip().lower()
                                if any(term in p_txt for term in ["bachelor", "bachelors", "b.tech", "btech", "b.e", "undergraduate"]):
                                    pop.click()
                                    clicked = True
                                    break
                        if not clicked:
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
                        # Check if custom dropdown is for Education / Degree
                        is_education = (
                            any(w in question.lower() for w in ["education", "degree", "qualification", "highest level"]) or
                            "bachelor" in answer.lower() or
                            any("bachelor" in o.inner_text().lower() for o in options) or
                            (any("master" in o.inner_text().lower() for o in options) and any(d in o.inner_text().lower() for o in options for d in ["school", "diploma", "doctor", "secondary"]))
                        )
                        if not chosen and is_education:
                            # 1. Top priority: Strictly Bachelor's / Bachelors / Bachelor (normalized for apostrophes)
                            for o in options:
                                o_clean = o.inner_text().strip().lower().replace("'", "").replace("’", "")
                                if "select" in o_clean or "choose" in o_clean:
                                    continue
                                if "bachelor" in o_clean:
                                    chosen = o
                                    print(f"    [Custom Dropdown Education] '{question}' -> Selected Bachelor's / Bachelors: '{o.inner_text().strip()}'")
                                    break
                            if not chosen:
                                for o in options:
                                    o_clean = o.inner_text().strip().lower()
                                    if any(term in o_clean for term in ["b.tech", "btech", "b.e", "undergraduate", "4-year"]):
                                        chosen = o
                                        print(f"    [Custom Dropdown Education] '{question}' -> Selected: '{o.inner_text().strip()}'")
                                        break
                            if not chosen:
                                for o in options:
                                    o_clean = o.inner_text().strip().lower()
                                    if any(bad in o_clean for bad in ["master", "doctor", "phd", "associate", "secondary", "high school", "diploma", "intermediate"]):
                                        continue
                                    if any(term in o_clean for term in ["graduate", "graduation", "college", "degree"]):
                                        chosen = o
                                        print(f"    [Custom Dropdown Education] '{question}' -> Selected: '{o.inner_text().strip()}'")
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
                                if (answer in ["6", "6 months"] or "6" in answer) and any(k in txt for k in ["6", "6 months", "6 month"]):
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
                    if (answer == "0" or "immediate" in answer) and any(k in radio_label for k in ["0", "immediate", "immediately", "less than", "15 days"]):
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
                    if (answer in ["6", "6 months"] or "6" in answer) and any(k in radio_label for k in ["6", "6 months", "6 month"]):
                        print(f"    [Radio Months] '{legend}' -> Checking: '{radio_label}'")
                        radio.check(force=True)
                        filled_ids.add(legend)
                        time.sleep(0.15)
                        break
                    if ("bachelor" in answer or any(w in legend.lower() for w in ["education", "degree", "qualification", "highest level"])) and any(k in radio_label.replace("'", "").replace("’", "") for k in ["bachelor", "b.tech", "btech", "b.e", "undergraduate", "4-year"]):
                        print(f"    [Radio Education] '{legend}' -> Checking Bachelor's / Bachelors: '{radio_label}'")
                        radio.check(force=True)
                        filled_ids.add(legend)
                        time.sleep(0.15)
                        break
            except Exception as e:
                print(f"    [Radio Error] {e}")

        # Also handle radio groups outside fieldset (e.g. Indeed div[role='radiogroup'] or named radio groups)
        try:
            all_radios = container.locator("input[type='radio']").all()
            grouped: Dict[str, List] = {}
            for r in all_radios:
                try:
                    if not r.is_visible():
                        continue
                    name = r.get_attribute("name") or "default_group"
                    grouped.setdefault(name, []).append(r)
                except Exception:
                    continue

            for name, r_list in grouped.items():
                if name in filled_ids:
                    continue
                # If any radio in group is already checked, skip
                if any(r.is_checked() for r in r_list):
                    filled_ids.add(name)
                    continue

                # Determine question from parent / ancestor or aria
                first_r = r_list[0]
                q_text = ""
                try:
                    parent_group = first_r.locator("xpath=ancestor::div[contains(@role, 'radiogroup') or contains(@class, 'ia-Questions-item') or contains(@class, 'form-group')][1]")
                    if parent_group.count() > 0:
                        aria_q = parent_group.get_attribute("aria-label") or parent_group.get_attribute("aria-labelledby") or ""
                        if aria_q and not aria_q.startswith("label-"):
                            q_text = aria_q
                        else:
                            lines = [ln.strip() for ln in parent_group.inner_text().split("\n") if ln.strip()]
                            if lines:
                                q_text = lines[0]
                except Exception:
                    pass

                if not q_text:
                    q_text = self._get_input_label(container, first_r) or name

                if not q_text or q_text in filled_ids:
                    continue

                ans = self.rag.answer_screening_question(q_text).lower()
                matched = False
                for r in r_list:
                    r_lbl = self._get_input_label(container, r).lower()
                    val = (r.get_attribute("value") or "").lower()
                    combo_desc = f"{r_lbl} {val}"
                    if ans in combo_desc or (ans == "yes" and "yes" in combo_desc) or (ans == "no" and "no" in combo_desc):
                        print(f"    [Radio Group] '{q_text}' -> Checking: '{r_lbl or val}'")
                        r.check(force=True)
                        matched = True
                        break
                    if (ans == "0" or "immediate" in ans) and any(k in combo_desc for k in ["0", "immediate", "immediately", "less than", "15 days"]):
                        print(f"    [Radio Group Joining] '{q_text}' -> Checking: '{r_lbl or val}'")
                        r.check(force=True)
                        matched = True
                        break
                    if ans == "2" and any(k in combo_desc for k in ["2", "1-3", "2-3", "2+"]):
                        print(f"    [Radio Group YOE] '{q_text}' -> Checking: '{r_lbl or val}'")
                        r.check(force=True)
                        matched = True
                        break
                    if (ans in ["6", "6 months"] or "6" in ans) and any(k in combo_desc for k in ["6", "6 months", "6 month"]):
                        print(f"    [Radio Group Months] '{q_text}' -> Checking: '{r_lbl or val}'")
                        r.check(force=True)
                        matched = True
                        break
                    if ("bachelor" in ans or any(w in q_text.lower() for w in ["education", "degree", "qualification", "highest level"])) and any(k in combo_desc.replace("'", "").replace("’", "") for k in ["bachelor", "b.tech", "btech", "b.e", "undergraduate", "4-year"]):
                        print(f"    [Radio Group Education] '{q_text}' -> Checking Bachelor's / Bachelors: '{r_lbl or val}'")
                        r.check(force=True)
                        matched = True
                        break

                if not matched and r_list:
                    print(f"    [Radio Group Fallback] '{q_text}' -> Checking first option")
                    r_list[0].check(force=True)

                filled_ids.add(name)
                filled_ids.add(q_text)
                time.sleep(0.15)
        except Exception as e:
            print(f"    [Radio Grouping Error] {e}")

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

                    // Never tick the "Follow company", email updates, or negative exclusion checkboxes
                    const emailKeywords = [
                        "email update", "email updates", "get email updates", "job alert", "job alerts",
                        "email me", "send me", "notify me", "similar jobs", "recommended jobs",
                        "stay updated", "receive updates", "job notifications", "alert me", "alerts"
                    ];
                    const isEmailUpdate = emailKeywords.some(kw => fullDesc.includes(kw));
                    const isExcluded = isEmailUpdate || fullDesc.includes("follow") || id.includes("follow") || name.includes("follow") ||
                                       fullDesc.includes("stay up to date") ||
                                       fullDesc.includes("previously worked") || fullDesc.includes("former employee") ||
                                       fullDesc.includes("referred by") || fullDesc.includes("employee referral") ||
                                       fullDesc.includes("serving notice") || fullDesc.includes("serving np") ||
                                       fullDesc.includes("misconduct") || fullDesc.includes("abandonment") ||
                                       fullDesc.includes("bankruptcy") || fullDesc.includes("financial delinquency") ||
                                       fullDesc.includes("litigation") || fullDesc.includes("decline") ||
                                       fullDesc.includes("opt out");
                    if (isExcluded) continue;

                    const isConsent = fullDesc.includes("consent") || 
                                     fullDesc.includes("agree") || 
                                     fullDesc.includes("terms") || 
                                     fullDesc.includes("privacy") || 
                                     fullDesc.includes("certify") || 
                                     fullDesc.includes("acknowledge") ||
                                     fullDesc.includes("declare") ||
                                     fullDesc.includes("declaration") ||
                                     fullDesc.includes("truthful") ||
                                     fullDesc.includes("convicted") ||
                                     fullDesc.includes("criminal");

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
                                          fullDesc.includes("wfo") || fullDesc.includes("relocate") || fullDesc.includes("relocation") ||
                                          fullDesc.includes("willing to relocate") || fullDesc.includes("4/5") || fullDesc.includes("4-5") ||
                                          fullDesc.includes("5 days") || fullDesc.includes("4 days") || fullDesc.includes("days a week") ||
                                          fullDesc.includes("setting") || fullDesc.includes("eligible") || fullDesc.includes("requirements") ||
                                          fullDesc.includes("qualifications") || fullDesc.includes("jd") || fullDesc.includes("authorized") ||
                                          fullDesc.includes("degree") || fullDesc.includes("bachelor") || fullDesc.includes("graduate");

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

                // Check for standalone visible labels with text like 'I consent' or 'I agree' or 'willing to relocate'
                const labels = Array.from(document.querySelectorAll("label, span.artdeco-checkbox__label"));
                for (const lbl of labels) {
                    const txt = (lbl.innerText || "").toLowerCase().trim();
                    if (txt.includes("follow") || txt.includes("previously worked")) continue;
                    
                    const isTargetLabel = txt === "i consent" || txt === "i agree" || txt.startsWith("i consent") ||
                                          txt.startsWith("i agree") || txt.includes("consent") || txt.includes("terms and conditions") ||
                                          txt.includes("relocate") || txt.includes("relocation") || txt.includes("willing to relocate") ||
                                          txt.includes("4/5 days") || txt.includes("hybrid setting") || txt.includes("onsite");

                    if (isTargetLabel) {
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

            # 2. Secondary Strategy: Playwright locators for labels containing "I consent", "consent", "I agree", "relocate", etc.
            consent_label_selectors = [
                "label:has-text('I consent')",
                "label:has-text('consent')",
                "label:has-text('I agree')",
                "label:has-text('agree to')",
                "label:has-text('relocate')",
                "label:has-text('relocation')",
                "label:has-text('willing to relocate')",
                "label:has-text('4/5 days')",
                "label:has-text('hybrid setting')",
                "span.artdeco-checkbox__label:has-text('consent')",
                "span.artdeco-checkbox__label:has-text('agree')",
                "span.artdeco-checkbox__label:has-text('relocate')",
                "span.artdeco-checkbox__label:has-text('relocation')"
            ]
            for scope in [container, page]:
                for sel in consent_label_selectors:
                    try:
                        labels = scope.locator(sel).all()
                        for lbl in labels:
                            if not lbl.is_visible():
                                continue
                            txt = lbl.inner_text().lower().strip()
                            excluded_terms = [
                                "follow", "previously worked", "former employee",
                                "referred by", "employee referral", "serving notice", "decline", "opt out",
                                "email update", "email updates", "get email updates", "job alert", "job alerts",
                                "email me", "send me", "notify me", "similar jobs", "recommended jobs",
                                "stay up to date", "stay updated", "receive updates", "notifications", "alerts",
                                "misconduct", "abandonment", "bankruptcy", "financial delinquency", "litigation"
                            ]
                            if any(ex in txt for ex in excluded_terms):
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
                            if "follow" in desc or cb_id == "follow-company-checkbox" or any(ex in desc for ex in excluded_terms):
                                continue
                            if not cb.is_checked():
                                print(f"    [Checkbox] Force checking input: #{cb_id}")
                                cb.check(force=True)
                                time.sleep(0.15)
                        except Exception:
                            continue
                except Exception:
                    pass

            # Final check: always ensure follow company and email updates checkboxes remain unchecked
            self._uncheck_follow_company(container, page)
            self._uncheck_email_updates(container, page)

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

    def _uncheck_email_updates(self, container, page: Page) -> bool:
        """
        Ensures that 'Get email updates...', 'Job alerts', and similar promotional/alert
        checkboxes are NEVER checked on Indeed, LinkedIn, or any company application.
        If pre-checked by the platform, unchecks them cleanly.
        """
        unchecked_any = False
        try:
            # 1. Primary Strategy: In-page DOM evaluation to locate & uncheck checked email/alert checkboxes
            res = page.evaluate("""() => {
                const keywords = [
                    "email update", "email updates", "get email updates", "job alert", "job alerts",
                    "email me", "send me jobs", "send me alerts", "notify me", "similar jobs",
                    "recommended jobs", "stay updated", "receive updates", "job notifications",
                    "alert me", "new jobs like this", "get notified"
                ];
                let count = 0;
                const checkboxes = Array.from(document.querySelectorAll("input[type='checkbox']"));
                for (const cb of checkboxes) {
                    const id = (cb.id || "").toLowerCase();
                    const name = (cb.name || "").toLowerCase();
                    const aria = (cb.getAttribute("aria-label") || "").toLowerCase();
                    const label = document.querySelector(`label[for='${cb.id}']`) || cb.closest("label");
                    const labelText = label ? label.innerText.toLowerCase() : "";
                    const parentText = cb.parentElement ? cb.parentElement.innerText.toLowerCase() : "";
                    const fullDesc = (id + " " + name + " " + aria + " " + labelText + " " + parentText).toLowerCase();

                    const isMatch = keywords.some(k => fullDesc.includes(k));
                    if (isMatch) {
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
                            count++;
                        }
                    }
                }
                return count;
            }""")
            if res and int(res) > 0:
                print(f"    [Email Updates] Successfully unchecked {res} 'Get email updates / job alerts' checkbox(es) via DOM!")
                unchecked_any = True
                time.sleep(0.2)

            # 2. Secondary Strategy: Playwright locators for email updates / job alert checkboxes & labels
            email_selectors = [
                "input[id*='email-update' i]",
                "input[id*='email_update' i]",
                "input[id*='job-alert' i]",
                "input[id*='job_alert' i]",
                "input[id*='alert' i]",
                "input[name*='emailUpdate' i]",
                "input[name*='jobAlert' i]",
                "input[aria-label*='email update' i]",
                "input[aria-label*='job alert' i]",
                "input[aria-label*='email' i][aria-label*='update' i]"
            ]
            search_scopes = [container]
            if container != page:
                search_scopes.append(page)

            for scope in search_scopes:
                for sel in email_selectors:
                    try:
                        cbs = scope.locator(sel).all()
                        for cb in cbs:
                            if cb.is_checked():
                                print(f"    [Email Updates] Unchecking checkbox via Playwright: {sel}")
                                cb.uncheck(force=True)
                                unchecked_any = True
                                time.sleep(0.15)
                    except Exception:
                        continue

            # Check visible labels mentioning email updates / job alerts
            label_patterns = [
                "label:has-text('email updates')",
                "label:has-text('Email updates')",
                "label:has-text('Get email updates')",
                "label:has-text('job alerts')",
                "label:has-text('Job alerts')",
                "label:has-text('send me jobs')",
                "label:has-text('Send me jobs')",
                "label:has-text('Send me job alerts')",
                "span:has-text('Get email updates')",
                "span:has-text('email updates for jobs like this')"
            ]
            for scope in search_scopes:
                for lsel in label_patterns:
                    try:
                        lbls = scope.locator(lsel).all()
                        for lbl in lbls:
                            if not lbl.is_visible():
                                continue
                            # Find associated input
                            for_id = lbl.get_attribute("for")
                            cb = None
                            if for_id:
                                cb = scope.locator(f"#{for_id}").first
                            else:
                                cb = lbl.locator("input[type='checkbox']").first
                            
                            if cb and cb.count() > 0 and cb.is_checked():
                                print(f"    [Email Updates] Unchecking via label click: '{lbl.inner_text().strip()[:40]}'")
                                lbl.click(force=True)
                                unchecked_any = True
                                time.sleep(0.15)
                    except Exception:
                        continue

        except Exception as e:
            print(f"    [Uncheck Email Updates Error] {e}")

        return unchecked_any

    def _is_legitimate_wizard_button(self, loc) -> bool:
        """
        Validates that a button or submit element is a legitimate wizard advancement button
        and NOT a header navigation link, close button, or exit link.
        """
        try:
            if not loc or loc.count() == 0 or not loc.is_visible():
                return False

            # Exclude exit, close, and feedback buttons
            data_testid = (loc.get_attribute("data-testid") or "").lower()
            if any(bad in data_testid for bad in ["exit", "close", "feedback", "dismiss", "cancel"]):
                return False

            btn_id = (loc.get_attribute("id") or "").lower()
            if any(bad in btn_id for bad in ["exit", "close", "feedback", "dismiss", "cancel", "accountmenu", "companyreviews"]):
                return False

            # Exclude links (<a> tags) navigating to companies, gnav, home, salary guide
            href = (loc.get_attribute("href") or "").lower()
            if href and any(bad in href for bad in ["companies", "gnav", "salary", "messages", "hire", "notifications", "/?from="]):
                return False

            txt = loc.inner_text().lower().strip()
            if any(bad in txt for bad in ["company reviews", "salary guide", "save and close", "report an issue", "skip to main", "employers / post job"]):
                return False

            # Exclude elements inside top navigation, header, or footer feedback/exit links
            in_header = loc.evaluate("""e => {
                return e.closest("header, nav, [class*='gnav'], [id*='gnav'], [data-gnav-element], .ia-Navigation") !== null;
            }""")
            if in_header:
                return False

            return True
        except Exception:
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
            already_applied = page.locator(
                "span.artdeco-inline-feedback:has-text('Applied'), "
                "button:has-text('Applied'), "
                "div:has-text('You applied on Indeed'), "
                "div:has-text('Application submitted'), "
                "span:has-text('Application submitted'), "
                "p:has-text('Application submitted'), "
                "h3:has-text('Application status'), "
                "[data-testid*='applied']"
            ).first
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
                    "button:has-text('Easy Apply')",
                    "button[aria-label*='Easy Apply' i]",
                    "button.jobs-apply-button",
                    ".jobs-apply-button--top-card button",
                    ":is(button, div[role='button']):has-text('Easy Apply')",
                    ":is(button, div[role='button'])[aria-label*='Easy Apply' i]",
                    ".jobs-apply-button--top-card"
                ]

            apply_query = ", ".join(apply_selectors)
            
            # Wait up to 15s for the button to appear after page loads
            try:
                page.wait_for_selector(apply_query, state="visible", timeout=15000)
            except Exception:
                pass

            # Find the first actually visible apply button
            apply_btn = None
            for sel in apply_selectors:
                try:
                    locs = page.locator(sel).all()
                    for loc in locs:
                        if loc.is_visible():
                            apply_btn = loc
                            break
                    if apply_btn:
                        break
                except Exception:
                    continue
            
            if not apply_btn or not apply_btn.is_visible():
                result["error"] = f"No Direct / Easy Apply button visible on {platform_name} (may require login or external redirect)"
                page.screenshot(path=str(SCREENSHOTS_DIR / f"{platform_name.lower()}_no_apply_found.png"))
                page.close()
                return result

            result["easy_apply_found"] = True
            print(f"Found {platform_name} Apply button! Clicking...")
            
            apply_page = page
            if is_indeed:
                try:
                    with page.expect_popup(timeout=3000) as popup_info:
                        apply_btn.click()
                    apply_page = popup_info.value
                    print("Indeed opened application in a dedicated application window.")
                    apply_page.wait_for_load_state("domcontentloaded")
                    time.sleep(2)
                except Exception:
                    time.sleep(2)
            else:
                try:
                    apply_btn.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    apply_btn.click()
                except Exception:
                    apply_btn.click(force=True)
                time.sleep(2)

            # Wait for modal / dialog / iframe to appear
            for _ in range(8):
                container = self._get_active_container(apply_page)
                if container != apply_page:
                    break
                time.sleep(0.4)

            # Check if LinkedIn daily limit modal appeared
            limit_modal = apply_page.locator("dialog:has-text('Easy Apply limit'), div.artdeco-modal:has-text('Easy Apply limit'), [role='dialog']:has-text('Easy Apply limit'), h2:has-text('Easy Apply limit'), p:has-text('limit Easy Apply')").first
            if limit_modal.count() > 0 and limit_modal.is_visible():
                print("\n[!] LinkedIn Daily Easy Apply Limit Reached: 'You reached today\\'s Easy Apply limit'")
                result["status"] = "daily_limit_reached"
                result["error"] = "LinkedIn daily Easy Apply limit reached. Resume applications tomorrow."
                apply_page.screenshot(path=str(SCREENSHOTS_DIR / "linkedin_daily_limit_reached.png"))
                apply_page.close()
                return result

            container = self._get_active_container(apply_page)
            print(f"{platform_name} application container detected!")

            # Track filled fields per session to avoid flickering and focus stealing
            filled_ids: Set[str] = set()

            # Step through application wizard
            max_steps = 10
            for step in range(1, max_steps + 1):
                print(f"\n--- [{platform_name} Step {step}] ---")
                
                # Dynamically re-detect container on each step to avoid stale DOM references
                container = self._get_active_container(apply_page)

                # Smooth filling without focus jumps or screen flicker
                self._fill_text_inputs(container, filled_ids)
                self._fill_select_dropdowns(container, filled_ids)
                self._fill_custom_comboboxes(container, filled_ids)
                self._fill_radio_buttons(container, filled_ids)
                self._fill_consent_checkboxes(container, apply_page, filled_ids)
                self._handle_file_uploads(container)
                self._uncheck_follow_company(container, apply_page)
                self._uncheck_email_updates(container, apply_page)
                time.sleep(0.8)

                # Capture step screenshot
                step_img = SCREENSHOTS_DIR / f"{platform_name.lower()}_step_{step}.png"
                apply_page.screenshot(path=str(step_img))

                # Comprehensive button selectors for both platforms (Indeed & LinkedIn)
                # Wait for any async hydration / loading spinner to clear before button evaluation
                for _ in range(8):
                    try:
                        loading_el = apply_page.locator("*:has-text('Preparing review'), *:has-text('loading'), .ia-LoadingSpinner, [aria-label*='Loading']").first
                        if loading_el.count() > 0 and loading_el.is_visible():
                            time.sleep(1)
                            continue
                    except Exception:
                        pass
                    break

                # Comprehensive button selectors for both platforms (Indeed & LinkedIn)
                submit_selectors = [
                    "button[data-testid='submit-application-button']",
                    "button[data-testid*='submit']",
                    "button:has-text('Submit your application')",
                    "button:has-text('Submit application')",
                    "button:has-text('Submit')",
                    "button[aria-label*='Submit application']",
                    "button[aria-label*='Submit']",
                    "input[type='submit'][value*='Submit']"
                ]
                review_selectors = [
                    "button[data-testid='review-application-button']",
                    "button[data-testid*='review']",
                    "button:has-text('Review your application')",
                    "button:has-text('Review application')",
                    "button:has-text('Review'):not(:has-text('Company'))",
                    "button[aria-label*='Review your application']",
                    "button[aria-label*='Review']"
                ]
                next_selectors = [
                    "button[data-testid='continue-button']",
                    "button[data-testid='save-and-continue-button']",
                    "button[data-testid*='continue']",
                    "button.ia-continueButton",
                    "button:has-text('Continue to next step')",
                    "button:has-text('Save and continue')",
                    "button:has-text('Continue to application')",
                    "button:has-text('Continue')",
                    "input[type='submit'][value*='Continue']",
                    "input[type='submit'][value*='Next']",
                    "button[type='submit']:has-text('Continue')",
                    "button[type='submit']:has-text('Next')",
                    "button[aria-label*='Continue to next step']",
                    "button[aria-label*='Continue']",
                    "button:has-text('Next')",
                    "button[aria-label*='Next']",
                    "button:has-text('Proceed')"
                ]

                submit_btn = None
                review_btn = None
                next_btn = None

                search_scopes = [container]
                if container != apply_page:
                    search_scopes.append(apply_page)
                for f in apply_page.frames:
                    if f not in search_scopes:
                        search_scopes.append(f)

                for wait_attempt in range(8):
                    # 1. Check for Submit
                    for scope in search_scopes:
                        for sel in submit_selectors:
                            try:
                                loc = scope.locator(sel).first
                                if self._is_legitimate_wizard_button(loc):
                                    submit_btn = loc
                                    break
                            except Exception:
                                pass
                        if submit_btn:
                            break
                    if submit_btn:
                        break

                    # 2. Check for Review
                    for scope in search_scopes:
                        for sel in review_selectors:
                            try:
                                loc = scope.locator(sel).first
                                if self._is_legitimate_wizard_button(loc):
                                    review_btn = loc
                                    break
                            except Exception:
                                pass
                        if review_btn:
                            break
                    if review_btn:
                        break

                    # 3. Check for Next / Continue
                    for scope in search_scopes:
                        for sel in next_selectors:
                            try:
                                loc = scope.locator(sel).first
                                if self._is_legitimate_wizard_button(loc):
                                    next_btn = loc
                                    break
                            except Exception:
                                pass
                        if next_btn:
                            break
                    if next_btn:
                        break

                    time.sleep(1)

                if submit_btn:
                    print(f"Reached final step! 'Submit' button is visible on {platform_name}.")
                    # Ensure any final consent / agreement checkbox is ticked
                    self._fill_consent_checkboxes(container, apply_page, filled_ids)
                    # Always uncheck 'Follow company' and 'Email updates' checkboxes before submitting
                    self._uncheck_follow_company(container, apply_page)
                    self._uncheck_email_updates(container, apply_page)
                    time.sleep(0.3)
                    
                    review_file = SCREENSHOTS_DIR / f"{platform_name.lower()}_before_submit_{int(time.time())}.png"
                    apply_page.screenshot(path=str(review_file))
                    
                    if auto_submit:
                        self._uncheck_follow_company(container, apply_page)
                        self._uncheck_email_updates(container, apply_page)
                        print(f"Clicking 'Submit' on {platform_name}...")
                        try:
                            submit_btn.scroll_into_view_if_needed()
                            time.sleep(0.2)
                            submit_btn.click()
                        except Exception:
                            submit_btn.click(force=True)
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
                    btn_text = "Review"
                    try:
                        btn_text = review_btn.inner_text().strip() or "Review"
                    except Exception:
                        pass
                    print(f"Found '{btn_text}' button! Advancing to review page...")
                    try:
                        review_btn.scroll_into_view_if_needed()
                        time.sleep(0.2)
                        review_btn.click()
                    except Exception:
                        review_btn.click(force=True)
                    time.sleep(2.5)
                    continue

                if next_btn:
                    btn_text = "Continue"
                    try:
                        btn_text = next_btn.inner_text().strip() or "Continue"
                    except Exception:
                        pass
                    print(f"Found '{btn_text}' button! Advancing...")
                    try:
                        next_btn.scroll_into_view_if_needed()
                        time.sleep(0.2)
                        next_btn.click()
                    except Exception:
                        next_btn.click(force=True)
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
