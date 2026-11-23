"""Stable application entry point for HTTP and Socket.IO adapters."""
from netmon.domain.alerts import AlertManager
from netmon.infra.config import Settings
from netmon.infra.crypto import Crypto
from netmon.infra.db import Database
from netmon.infra.repositories import SqlAlertRepository
from .alerts import AlertService
from .audit import AuditService
from .auth import AuthService
from .config import ConfigService
from .discovery import DiscoveryService
from .errors import AuthError, ValidationError
from .gns3 import Gns3Service
from .inventory import InventoryService
from .monitor import MonitorService
from .reports import ReportService
from .settings import SettingsService


class NetMonService:
    @classmethod
    def create(cls, db_url, fernet_key, publisher, start_scheduler=True):
        service = cls()
        environment = Settings()
        service.db = Database(db_url)
        service.db.init_db()
        service.crypto = Crypto(fernet_key)
        service.audit = AuditService(service.db)
        service.settings = SettingsService(service.db, service.audit)
        service.auth = AuthService(service.db, service.audit)
        service.inventory = InventoryService(service.db, service.audit)
        repository = SqlAlertRepository(service.db)
        service.alerts = AlertService(service.db, service.audit, service.crypto, publisher, repository)
        manager = AlertManager(repository=repository, on_change=service.alerts.on_change)
        service.alerts.manager = manager
        service.alerts.reload_notifiers()
        service.monitor = MonitorService(service.db, service.audit, service.settings, service.inventory, publisher, manager)
        service.inventory.monitor = service.monitor
        service.config = ConfigService(service.db, service.audit, service.crypto, service.alerts)
        service.monitor.config = service.config
        service.reports = ReportService(service.db, service.inventory)
        service.discovery = DiscoveryService(service.inventory, service.audit)
        service.gns3 = Gns3Service(environment.GNS3_URL, service.inventory, service.audit)
        service.auth.seed_admin(environment.ADMIN_USERNAME, environment.ADMIN_PASSWORD)
        if start_scheduler:
            service.monitor.start()
        return service

    def seed_demo(self, actor=None):
        if self.inventory.list_devices()["total"]:
            return {"created": 0}
        root = self.inventory.create_group("Tòa A", actor=actor)
        floor2 = self.inventory.create_group("Tầng 2", root["id"], actor)
        floor3 = self.inventory.create_group("Tầng 3", root["id"], actor)
        for name, ip, kind, group in (("Router Demo", "127.0.0.1", "router", floor2["id"]),
                ("Server Demo", "1.1.1.1", "server", floor2["id"]),
                ("PC Demo", "8.8.8.8", "pc", floor3["id"])):
            device = self.inventory.create_device({"name": name, "ip": ip, "device_type": kind, "group_id": group}, actor)
            self.config.save_credentials(device["id"], {"protocol": "fake", "username": "demo", "password": "demo", "driver": "vyos"}, actor)
        self.audit.log(actor, "demo_seed", "inventory")
        return {"created": 3}

    def close(self):
        self.discovery.close()
        self.monitor.close()
        self.db.close()
