"""
Ikigai Masala - Menu Planning Application

Single entry point. Run with:
    python -m streamlit run app.py
"""

# Re-export the Streamlit app so `streamlit run app.py` works from the project root.
# The streamlit_app module auto-starts the Flask API backend in a background thread.

from ui.streamlit_app import *  # noqa: F401,F403
