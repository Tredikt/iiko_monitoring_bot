from services.analytics import AnalyticsService

_analytics_service: AnalyticsService = None


def set_analytics_service(service: AnalyticsService):
    global _analytics_service
    _analytics_service = service


def get_analytics_service() -> AnalyticsService:
    return _analytics_service

