#!/bin/bash
# بکاپ رمزنگاری‌شده‌ی روزانه‌ی دیتابیس (دیتابیس هیچ اطلاعات ورودی ندارد، ولی شماره پرونده‌ها را دارد)
# رمز بکاپ در ~/.backup_pass (chmod 600) — نگهداری ۱۴ روز
set -e
cd /home/bot/Legal-Automation
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M)
sqlite3 data/legal.db ".backup backups/legal-$STAMP.db"
gpg --batch --yes --pinentry-mode loopback --passphrase-file /home/bot/.backup_pass \
    -c -o "backups/legal-$STAMP.db.gpg" "backups/legal-$STAMP.db"
rm -f "backups/legal-$STAMP.db"
find backups -name "legal-*.db.gpg" -mtime +14 -delete
