import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

import repo
import security

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return render_template("register.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    full_name = (request.form.get("full_name") or "").strip()

    if not EMAIL_RE.match(email):
        flash("Email tidak valid.", "error")
        return render_template("register.html", email=email, full_name=full_name)
    if len(password) < 8:
        flash("Password minimal 8 karakter.", "error")
        return render_template("register.html", email=email, full_name=full_name)
    if repo.get_user_by_email(email):
        flash("Email sudah terdaftar. Coba login.", "error")
        return render_template("register.html", email=email, full_name=full_name)

    password_hash = security.hash_password(password)
    user_id = repo.create_user(email, password_hash, role="CLIENT_OWNER", full_name=full_name or None)
    user = repo.get_user_by_email(email)
    security.login_user(user)
    return redirect(url_for("client.dashboard"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if security.is_login_rate_limited(email):
        flash("Terlalu banyak percobaan login gagal. Coba lagi dalam beberapa menit.", "error")
        return render_template("login.html", email=email)

    user = repo.get_user_by_email(email)

    if not user or not security.verify_password(user["password_hash"], password):
        security.record_failed_login(email)
        flash("Email atau password salah.", "error")
        return render_template("login.html", email=email)

    security.clear_login_attempts(email)
    security.login_user(user)
    if user["role"] == "KILAS_ADMIN":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("client.dashboard"))


@auth_bp.route("/logout")
def logout_page():
    security.logout_user()
    return redirect(url_for("auth.login_page"))
