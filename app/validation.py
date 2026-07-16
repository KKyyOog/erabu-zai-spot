def first_overlong_field(data, limits):
    """Return the first field whose string value exceeds its configured limit."""
    for field, max_length in limits.items():
        value = data.get(field, "")
        if value is not None and len(str(value)) > max_length:
            return field, max_length
    return None
