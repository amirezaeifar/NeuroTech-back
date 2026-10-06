"""Bilingual transactional email copy."""


def account_verification(link: str) -> tuple[str, str]:
    return (
        "NeuroTech | Confirm your email / تأیید ایمیل",
        f"Verification link: {link}\n\n"
        "به نوروتک خوش آمدید. برای فعال‌سازی حساب، لینک بالا را ظرف ۲۴ ساعت باز کنید.\n"
        "اگر این درخواست را ثبت نکرده‌اید، این پیام را نادیده بگیرید.\n\n"
        "Welcome to NeuroTech. Open the link above within 24 hours to activate your account.\n"
        "If you did not request this, ignore this message.",
    )


def event_reservation(title: str, link: str) -> tuple[str, str]:
    return (
        "NeuroTech | Confirm your event reservation / تأیید رزرو رویداد",
        f"Event / رویداد: {title}\n"
        f"Confirmation link / لینک تأیید: {link}\n\n"
        "برای ثبت نهایی رزرو و دسترسی به صفحهٔ رویداد، لینک را ظرف ۲۴ ساعت باز کنید. "
        "ظرفیت هنگام تأیید دوباره بررسی می‌شود.\n\n"
        "Open the link within 24 hours to complete your reservation and access the event. "
        "Availability is checked again when you confirm.\n\n"
        "اگر این درخواست را ثبت نکرده‌اید، این پیام را نادیده بگیرید.\n"
        "If you did not request this, ignore this message.",
    )
