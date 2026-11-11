def display_name(user):
    name = user.get("name")
    return name.title() if name is not None else ""