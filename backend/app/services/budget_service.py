"""Pure budget arithmetic. Kept side-effect free for easy testing."""


def compute_new_budget(current: float | None, operation: str, amount: float) -> float:
    """Apply a budget operation and return the new value.

    Operations:
      add:      current + amount
      subtract: max(0, current - amount)
      set:      amount (replace)
      reset:    0 (amount ignored)

    Result is rounded to 2 decimal places. Negative current is treated as 0.
    """
    base = current if current is not None and current > 0 else 0.0
    if operation == "add":
        new_value = base + amount
    elif operation == "subtract":
        new_value = max(0.0, base - amount)
    elif operation == "set":
        new_value = amount
    elif operation == "reset":
        new_value = 0.0
    else:
        raise ValueError(f"Unknown budget operation: {operation}")
    return round(new_value, 2)
