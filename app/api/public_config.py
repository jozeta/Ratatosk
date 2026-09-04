from fastapi import APIRouter

from app.core.dynamic_settings import get_settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def public_config():
    cfg = get_settings()
    return {
        "brand_name": cfg["brand_name"],
        "brand_logo_filename": cfg["brand_logo_filename"],
        "footer_text": cfg["footer_text"],
        "allow_anonymous_upload": cfg["allow_anonymous_upload"],
        "allow_anonymous_download": cfg["allow_anonymous_download"],
        "allow_user_registration": cfg["allow_user_registration"],
        "allow_user_login": cfg["allow_user_login"],
        "enable_user_sharing": cfg["enable_user_sharing"],
        "enable_api_keys": cfg["enable_api_keys"],
        "enable_user_management": cfg["enable_user_management"],
        "enable_file_management": cfg["enable_file_management"],
        "enable_multi_file_upload": cfg["enable_multi_file_upload"],
        "allow_secondary_password": cfg["allow_secondary_password"],
        "enforce_secondary_password": cfg["enforce_secondary_password"],
        "enable_mfa": cfg["enable_mfa"],
        "password_min_length": cfg["password_min_length"],
        "password_require_uppercase": cfg["password_require_uppercase"],
        "password_require_lowercase": cfg["password_require_lowercase"],
        "password_require_number": cfg["password_require_number"],
        "password_require_special": cfg["password_require_special"],
        "max_file_size_mb": cfg["max_file_size_mb"],
        "chunk_size_mb": cfg["chunk_size_mb"],
        "extension_rule_mode": cfg["extension_rule_mode"],
        "extension_list": cfg["extension_list"],
        "allowed_ttl_presets": cfg["allowed_ttl_presets"],
        "default_ttl": cfg["default_ttl"],
        "allow_custom_ttl": cfg["allow_custom_ttl"],
        "allow_burn_after_download": cfg["allow_burn_after_download"],
        "force_burn_after_download": cfg["force_burn_after_download"],
        "default_max_downloads": cfg["default_max_downloads"],
        "allow_custom_max_downloads": cfg["allow_custom_max_downloads"],
        "hide_upload_link": cfg["hide_upload_link"],
        "hide_download_link": cfg["hide_download_link"],
        "custom_theme_enabled": cfg["custom_theme_enabled"],
        "custom_theme_paper": cfg["custom_theme_paper"],
        "custom_theme_surface": cfg["custom_theme_surface"],
        "custom_theme_navbar_bg": cfg["custom_theme_navbar_bg"],
        "custom_theme_border": cfg["custom_theme_border"],
        "custom_theme_text": cfg["custom_theme_text"],
        "custom_theme_accent": cfg["custom_theme_accent"],
        "custom_theme_danger": cfg["custom_theme_danger"],
        "custom_theme_heading_color": cfg["custom_theme_heading_color"],
        "custom_theme_heading_scale": cfg["custom_theme_heading_scale"],
        "custom_theme_body_scale": cfg["custom_theme_body_scale"],
        "password_reset_enabled": cfg["smtp_enabled"],
        "enable_download_notifications": cfg["enable_download_notifications"],
    }
