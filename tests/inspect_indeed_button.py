import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
from src.config import BROWSER_USER_DATA_DIR

url = 'https://in.indeed.com/viewjob?jk=eb7c81fcf8303125'
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_USER_DATA_DIR),
        channel='chrome',
        headless=True,
        args=['--disable-blink-features=AutomationControlled']
    )
    pg = ctx.new_page()
    pg.goto(url, wait_until='domcontentloaded', timeout=30000)
    print('Title:', pg.title())
    
    loc1 = pg.get_by_role('button', name='Apply now')
    loc2 = pg.locator("button:has-text('Apply now')")
    loc3 = pg.locator("a:has-text('Apply now')")
    loc4 = pg.locator("[id*='indeedApplyButton']")
    loc5 = pg.locator("[data-testid*='indeedApply']")
    loc6 = pg.locator(".ia-IndeedApplyButton")

    print('loc1 (get_by_role):', loc1.count(), 'visible:', loc1.first.is_visible() if loc1.count() else False)
    print('loc2 (button:has-text):', loc2.count(), 'visible:', loc2.first.is_visible() if loc2.count() else False)
    print('loc3 (a:has-text):', loc3.count(), 'visible:', loc3.first.is_visible() if loc3.count() else False)
    print('loc4 (id*indeedApplyButton):', loc4.count(), 'visible:', loc4.first.is_visible() if loc4.count() else False)
    print('loc5 (data-testid):', loc5.count(), 'visible:', loc5.first.is_visible() if loc5.count() else False)
    print('loc6 (.ia-IndeedApplyButton):', loc6.count(), 'visible:', loc6.first.is_visible() if loc6.count() else False)

    # Let's also print all elements that have text 'Apply'
    all_apply = pg.locator("*:has-text('Apply now')").all()
    print('All elements with text Apply now:', len(all_apply))
    for el in all_apply[-3:]:
        print('  Tag:', el.evaluate("e => e.tagName"), 'Class:', el.get_attribute("class"), 'Id:', el.get_attribute("id"))

    ctx.close()
