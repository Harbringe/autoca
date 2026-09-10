"""Email + password authentication.

Deliberately runs the password hasher even when no user matches, so that a
wrong-email response takes the same time as a wrong-password one. Without it,
the login endpoint is a user-enumeration oracle -- which for a CA firm product
leaks the client list of every firm on the platform.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password


class EmailBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        email = (username or kwargs.get("email") or "").strip().lower()
        if not email or not password:
            return None

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Equalise timing against the found-user path.
            User().set_password(password)
            return None

        if not check_password(password, user.password):
            return None
        if not self.user_can_authenticate(user):
            return None
        return user

    @staticmethod
    def user_can_authenticate(user):
        return bool(user.is_active)

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return None
