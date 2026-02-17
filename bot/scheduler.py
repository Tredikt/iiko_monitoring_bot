import asyncio
from typing import Optional
from datetime import datetime, time
from aiogram import Bot
from config import settings
from services.analytics import AnalyticsService
from db.repo import SettingsRepo
import logging

logger = logging.getLogger(__name__)


class ReportScheduler:
    def __init__(self, bot: Bot, analytics_service: AnalyticsService):
        self.bot = bot
        self.analytics_service = analytics_service
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def send_daily_report(self):
        """Отправка ежедневного отчёта"""
        try:
            db_settings = await SettingsRepo.get_settings()
            
            today = datetime.now()
            today_metrics = await self.analytics_service.get_period_metrics(
                today.replace(hour=0, minute=0, second=0, microsecond=0),
                today
            )

            rolling_avg = await self.analytics_service.get_rolling_average(db_settings.rolling_days)
            today_revenue = today_metrics["revenue"]

            if rolling_avg > 0:
                change_pct = ((today_revenue - rolling_avg) / rolling_avg) * 100
                threshold = db_settings.alert_threshold_pct

                if change_pct <= -threshold:
                    emoji = "🔴"
                    alert_text = f"⚠️ АЛЕРТ: Падение выручки на {abs(change_pct):.1f}%"
                else:
                    emoji = "🟢"
                    alert_text = ""

                text = (
                    f"{emoji} Ежедневный отчёт\n\n"
                    f"{today_metrics['org_name']}\n"
                    f"Дата: {today.strftime('%Y-%m-%d')}\n\n"
                    f"🟢 Выручка: {today_revenue:,.0f} ₽\n"
                    f"🟢 Заказов: {today_metrics['orders']:,.0f}\n"
                    f"🟢 Средний чек: {today_metrics['average_check']:,.0f} ₽\n\n"
                    f"Средняя выручка за последние {db_settings.rolling_days} дней: {rolling_avg:,.0f} ₽\n"
                    f"Изменение к среднему: {change_pct:+.1f}%"
                )

                if alert_text:
                    text = f"{alert_text}\n\n{text}"

                await self.bot.send_message(
                    chat_id=settings.ADMIN_TG_ID,
                    text=text
                )
            else:
                await self.bot.send_message(
                    chat_id=settings.ADMIN_TG_ID,
                    text=f"🟢 Ежедневный отчёт\n\n{today_metrics['org_name']}\n"
                         f"Дата: {today.strftime('%Y-%m-%d')}\n\n"
                         f"🟢 Выручка: {today_revenue:,.0f} ₽\n"
                         f"🟢 Заказов: {today_metrics['orders']:,.0f}\n"
                         f"🟢 Средний чек: {today_metrics['average_check']:,.0f} ₽"
                )

        except Exception as e:
            logger.error(f"Error sending daily report: {e}")
            try:
                await self.bot.send_message(
                    chat_id=settings.ADMIN_TG_ID,
                    text=f"❌ Ошибка при формировании ежедневного отчёта: {str(e)}"
                )
            except:
                pass

    async def _scheduler_loop(self):
        """Фоновая задача для проверки времени и отправки отчётов"""
        last_sent_date = None
        
        while self._running:
            try:
                db_settings = await SettingsRepo.get_settings()
                report_hour, report_minute = map(int, db_settings.report_time.split(":"))
                report_time = time(report_hour, report_minute)
                
                now = datetime.now()
                current_time = now.time()
                current_date = now.date()
                
                # Проверяем, наступило ли время отправки и не отправляли ли уже сегодня
                if (current_time >= report_time and 
                    (last_sent_date is None or last_sent_date < current_date)):
                    await self.send_daily_report()
                    last_sent_date = current_date
                    logger.info(f"Daily report sent at {now.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Ждём 1 минуту перед следующей проверкой
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)

    def start(self):
        """Запуск фоновой задачи"""
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Report scheduler started")

    def shutdown(self):
        """Остановка фоновой задачи"""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Report scheduler stopped")

