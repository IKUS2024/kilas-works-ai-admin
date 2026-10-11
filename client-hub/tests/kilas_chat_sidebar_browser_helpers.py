"""Open the canonical conversation rail without changing navigation assertions."""
from playwright.sync_api import expect


def open_chat_sidebar(page):
    sidebar=page.locator('#premium-sidebar')
    if sidebar.evaluate('e=>e.inert'):
        page.locator('[data-premium-menu]').click()
    expect(sidebar.locator('[data-chat-sidebar]')).to_be_visible()
    return sidebar


def click_new_chat(page,agent=False,name='Chat baru'):
    sidebar=open_chat_sidebar(page)
    # Existing fixture deliberately leaves its old draft when beginning a new chat.
    def accept(dialog):dialog.accept()
    page.on('dialog',accept)
    try:
        new=sidebar.locator('[data-chat-sidebar] .ai-new')
        expect(new).to_have_accessible_name(name)
        assert new.evaluate('e=>e.tagName')==('BUTTON' if agent else 'A')
        new.click()
        page.wait_for_load_state('networkidle')
    finally:page.remove_listener('dialog',accept)
