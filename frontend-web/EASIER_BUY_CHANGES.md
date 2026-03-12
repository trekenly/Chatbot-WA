# Easier Buying — UX Helpers (v9)

This build adds three small changes aimed at reducing clicks and re-typing during purchase.

1) **Remember last FROM / TO**
   - The quick place chips include your most recent place (when available) as a one-tap option.
   - Stored in browser localStorage keys: `busx_last_from`, `busx_last_to`.

2) **More date shortcuts + remember last date**
   - Date quick chips now include your most recent date (when available), **Next Sat**, and **In 7 days**.
   - Stored in browser localStorage key: `busx_last_date`.

3) **Save & reuse passenger details**
   - Passenger details card shows **Use saved details** / **Clear saved** when a saved passenger exists.
   - Saves after you submit passenger details.
   - Stored in browser localStorage key: `busx_passenger`.
