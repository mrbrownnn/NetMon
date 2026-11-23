"""GNS3 view for the web: projects, nodes paired with NetMon devices, links, node start/stop/reload."""
from netmon.domain.gns3 import Gns3Client, Gns3Error
from .errors import ValidationError

ACTIONS = ("start", "stop", "reload")


class Gns3Service:
    def __init__(self, url, inventory, audit):
        self.url, self.inventory, self.audit = url, inventory, audit
        self.client = Gns3Client.create(url) if url else None

    def _client(self):
        if not self.client:
            raise ValidationError({"gns3": "Chưa cấu hình GNS3_URL"})
        return self.client

    def status(self):
        if not self.client:
            return {"configured": False, "demo": False, "url": None, "version": None, "error": None}
        try:
            version, error = self.client.version(), None
        except Gns3Error as e:
            version, error = None, str(e)
        return {"configured": True, "demo": self.url == "demo", "url": self.url, "version": version, "error": error}

    def projects(self):
        return self._client().projects()

    def project(self, project_id):
        client = self._client()
        nodes = client.nodes(project_id)
        # Pair by exact name: the device carries IP + SSH credentials, so its config tab reads the node's config.
        devices = {d["name"]: d for d in self.inventory.list_devices(paginated=False)}
        for n in nodes:
            d = devices.get(n["name"])
            n["device"] = {"id": d["id"], "name": d["name"], "ip": d["ip"], "status": d["status"]} if d else None
        names = {n["node_id"]: n["name"] for n in nodes}
        links = [{"link_id": link["link_id"], "ends": [{**e, "node_name": names.get(e["node_id"], e["node_id"])}
                  for e in link["nodes"]]} for link in client.links(project_id)]
        return {"nodes": sorted(nodes, key=lambda n: n["name"]), "links": links}

    def node_action(self, project_id, node_id, action, actor=None):
        if action not in ACTIONS:
            raise ValidationError({"action": "Thao tác không hợp lệ"})
        self._client().node_action(project_id, node_id, action)
        self.audit.log(actor, f"gns3_node_{action}", node_id, {"project_id": project_id})
        return {"ok": True}
