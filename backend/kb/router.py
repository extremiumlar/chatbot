"""Baza yo'naltiruvchisi: kb app modellari -> 'knowledge' bazasi.

Django'ning o'z jadvallari (auth, admin, inventory...) default bazada qoladi;
kb modellari esa bot bilan umumiy storage/knowledge.db ga o'qiydi/yozadi.
"""


class KnowledgeRouter:
    app_label = "kb"
    db_name = "knowledge"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.db_name
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.db_name
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # kb modellari faqat o'zaro bog'lanadi (Document <-> Chunk va h.k.)
        in_kb = (obj1._meta.app_label == self.app_label,
                 obj2._meta.app_label == self.app_label)
        if any(in_kb):
            return all(in_kb)
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Bot bazasini Django hech qachon migratsiya qilmasin (jadvallarni bot
        # o'zi yaratadi); kb app jadvallari default bazada ham yaratilmasin.
        if app_label == self.app_label or db == self.db_name:
            return False
        return None
