"""WSGI entry point: ``gunicorn wsgi:app`` or ``flask --app wsgi run``."""

from dagonservice import create_app

app = create_app()

if __name__ == "__main__":  # development server only
    app.run(host="127.0.0.1", port=57000)
