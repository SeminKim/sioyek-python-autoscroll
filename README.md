Script for auto-scrolling while mouse wheel is clicked.
Not so pretty but working.

Uses python wrapper of sioyek from: https://github.com/ahrm/sioyek-python-extensions


Install:
```
python -m pip install git+https://github.com/SeminKim/sioyek-python-autoscroll.git
```

Configs (middle click to search google scholar changed to shift middle click):
```
(prefs_user.config)
new_command _autoscroll python -m sioyek_autoscroll "%{sioyek_path}"
shift_middle_click_search_engine s
middle_click_search_engine 

(keys_user.config)
_autoscroll dd
```
