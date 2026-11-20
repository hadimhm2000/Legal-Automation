#!/bin/bash
# بکاپ رمزنگاری‌شده‌ی روزانه‌ی دیتابیس (دیتابیس هیچ اطلاعات ورودی ندارد، ولی شماره پرونده‌ها را دارد)
# رمز بکاپ در ~/.backup_pass (chmod 600) — نگهداری ۱۴ روز
set -euo pipefail
umask 077                                   # بکاپ‌ها فقط برای خود کاربر قابل خواندن باشند
cd /home/bot/Legal-Automation
mkdir -p backups
chmod 700 backups
STAMP=$(date +%Y%m%d-%H%M)
# اگر gpg شکست بخورد، نسخه‌ی رمزنشده‌ی دیتابیس روی دیسک نمی‌ماند
trap 'rm -f "backups/legal-$STAMP.db"' EXIT
sqlite3 data/legal.db ".backup backups/legal-$STAMP.db"
gpg --batch --yes --pinentry-mode loopback --passphrase-file /home/bot/.backup_pass \
    --cipher-algo AES256 -c -o "backups/legal-$STAMP.db.gpg" "backups/legal-$STAMP.db"
rm -f "backups/legal-$STAMP.db"
find backups -name "legal-*.db.gpg" -mtime +14 -delete
