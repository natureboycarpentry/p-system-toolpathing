"""Shared Fusion command-input helpers for dropdown controls."""


def read_dropdown(dropdown, default=None):
    """Return the selected dropdown item name, or default when none is selected."""
    if not dropdown:
        return default
    try:
        if dropdown.selectedItem:
            return dropdown.selectedItem.name
    except Exception:
        pass
    for index in range(dropdown.listItems.count):
        item = dropdown.listItems.item(index)
        if item.isSelected:
            return item.name
    return default


def select_dropdown(dropdown, name=None):
    """Select a dropdown item by name; fall back to the first item when name is missing."""
    if not dropdown or dropdown.listItems.count == 0:
        return
    if name:
        for index in range(dropdown.listItems.count):
            item = dropdown.listItems.item(index)
            item.isSelected = item.name == name
            if item.isSelected:
                return
    dropdown.listItems.item(0).isSelected = True
