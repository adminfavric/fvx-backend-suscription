from django.urls import path

from .views import MailTestView, ses_webhook

urlpatterns = [
    # POST /api/v1/email-events/ ← webhook que SNS llama con bounces/complaints/deliveries
    path("email-events/", ses_webhook, name="ses-webhook"),
    # POST /api/v1/mail-test/ ← test de envío para el showcase /components (dev-only).
    path("mail-test/", MailTestView.as_view(), name="mail-test"),
]
