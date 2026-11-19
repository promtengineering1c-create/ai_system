"""
Формы разового запроса прайса, регистрации с паролем и шагами анкеты, входа и запроса/установки нового пароля (с валидацией Honeypot и Captcha).
"""

from django import forms
from django.core.exceptions import ValidationError


class EmailPriceForm(forms.Form):
    email = forms.EmailField(
        label="Ваш Email",
        widget=forms.EmailInput(
            attrs={
                "placeholder": "example@domain.com",
                "required": True,
            }
        ),
    )
    # Скрытое поле-ловушка (Honeypot) для защиты от спам-ботов
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def clean_website(self) -> str:
        value = self.cleaned_data.get("website")
        if value:
            # Молчаливый отказ или стандартная ошибка валидации для ботов
            raise ValidationError("Обнаружена подозрительная активность.")
        return value

# TBD(depends: stages 7-8): Формы регистрации, входа, 3-шаговой анкеты подписки 
# и сброса пароля будут добавлены при реализации account_service и subscription_service.

