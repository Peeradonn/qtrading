"""Live engine: reconcile -> decide -> plan -> execute -> journal, once per hour.

The engine is the only code that places orders. It talks to an Exchange (paper or Roostoo), calls the same pure
strategy and the same plan_orders() the backtester uses, and never trades when anything looks wrong.
"""
