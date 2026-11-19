"""
backend/utils/forms.py
WTForms form definitions used across auth and public routes.
"""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, StringField, TextAreaField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Auth forms
# ---------------------------------------------------------------------------

class RegisterForm(FlaskForm):
    full_name = StringField(
        "Full Name",
        validators=[DataRequired(), Length(min=2, max=255)],
    )
    email = EmailField(
        "Email",
        validators=[DataRequired(), Email(check_deliverability=False), Length(max=255)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, max=72)],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )

    def validate_password(self, field):
        p = field.data or ""
        if not any(c.isupper() for c in p):
            raise ValidationError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in p):
            raise ValidationError("Password must contain at least one digit.")


class LoginForm(FlaskForm):
    email = EmailField(
        "Email",
        validators=[DataRequired(), Email(check_deliverability=False)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired()],
    )
    remember_me = BooleanField("Remember me")


class InviteCoordinatorForm(FlaskForm):
    full_name = StringField(
        "Full Name",
        validators=[DataRequired(), Length(min=2, max=255)],
    )
    email = EmailField(
        "Email",
        validators=[DataRequired(), Email(check_deliverability=False), Length(max=255)],
    )
    password = PasswordField(
        "Temporary Password",
        validators=[DataRequired(), Length(min=8, max=72)],
    )

    def validate_password(self, field):
        p = field.data or ""
        if not any(c.isupper() for c in p):
            raise ValidationError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in p):
            raise ValidationError("Password must contain at least one digit.")


# ---------------------------------------------------------------------------
# Public intake forms  (implemented in ST-12)
# ---------------------------------------------------------------------------

class IncidentReportForm(FlaskForm):
    description = TextAreaField(
        "Describe the incident",
        validators=[DataRequired(), Length(min=20, max=5000)],
    )
    location_hint = StringField(
        "Location (village / landmark)",
        validators=[Optional(), Length(max=255)],
    )
    contact = StringField(
        "Your name or contact (optional)",
        validators=[Optional(), Length(max=255)],
    )
    # Hidden fields populated by browser Geolocation API
    user_lat = StringField(validators=[Optional()])
    user_lng = StringField(validators=[Optional()])


class ReliefRequestForm(FlaskForm):
    description = TextAreaField(
        "Describe what is needed",
        validators=[DataRequired(), Length(min=10, max=5000)],
    )
    location_hint = StringField(
        "Location",
        validators=[Optional(), Length(max=255)],
    )
    contact = StringField(
        "Your name or contact (optional)",
        validators=[Optional(), Length(max=255)],
    )
    # Hidden fields populated by browser Geolocation API
    user_lat = StringField(validators=[Optional()])
    user_lng = StringField(validators=[Optional()])
