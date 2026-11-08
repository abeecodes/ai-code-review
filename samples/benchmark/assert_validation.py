def set_age(user, age):
    assert 0 <= age <= 150, "invalid age"
    user["age"] = age
    return user
