"""Testes automatizados da API (rode com: python test_app.py)."""
import os
import tempfile
import unittest

from app import app, init_db


class ChamadosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        app.config.update(TESTING=True, DATABASE=self.tmp.name)
        init_db()
        self.client = app.test_client()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def criar(self, **extra):
        dados = {"titulo": "PC não liga", "solicitante": "Ana", **extra}
        return self.client.post("/api/chamados", json=dados)

    def test_cria_com_status_aberto(self):
        r = self.criar(descricao="Tela preta")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json["status"], "aberto")

    def test_titulo_e_solicitante_obrigatorios(self):
        self.assertEqual(self.client.post("/api/chamados", json={"titulo": "x"}).status_code, 400)
        self.assertEqual(self.client.post("/api/chamados", json={"solicitante": "x"}).status_code, 400)

    def test_altera_status_e_filtra(self):
        id_ = self.criar().json["id"]
        self.criar(titulo="Outro")
        r = self.client.patch(f"/api/chamados/{id_}/status", json={"status": "resolvido"})
        self.assertEqual(r.json["status"], "resolvido")
        self.assertEqual(len(self.client.get("/api/chamados?status=resolvido").json), 1)
        self.assertEqual(len(self.client.get("/api/chamados?status=aberto").json), 1)
        self.assertEqual(len(self.client.get("/api/chamados").json), 2)

    def test_status_invalido_e_inexistente(self):
        id_ = self.criar().json["id"]
        self.assertEqual(self.client.patch(f"/api/chamados/{id_}/status", json={"status": "x"}).status_code, 400)
        self.assertEqual(self.client.patch("/api/chamados/999/status", json={"status": "aberto"}).status_code, 404)
        self.assertEqual(self.client.get("/api/chamados?status=x").status_code, 400)


    def test_prioridade_padrao_e_invalida(self):
        self.assertEqual(self.criar().json["prioridade"], "media")
        self.assertEqual(self.criar(prioridade="alta").json["prioridade"], "alta")
        self.assertEqual(self.criar(prioridade="urgentissima").status_code, 400)

    def test_ordena_e_filtra_por_prioridade(self):
        self.criar(titulo="B", prioridade="baixa")
        self.criar(titulo="A", prioridade="alta")
        self.criar(titulo="M", prioridade="media")
        titulos = [c["titulo"] for c in self.client.get("/api/chamados").json]
        self.assertEqual(titulos, ["A", "M", "B"])
        altas = self.client.get("/api/chamados?prioridade=alta").json
        self.assertEqual([c["titulo"] for c in altas], ["A"])
        self.assertEqual(self.client.get("/api/chamados?prioridade=x").status_code, 400)

    def test_altera_prioridade(self):
        id_ = self.criar().json["id"]
        r = self.client.patch(f"/api/chamados/{id_}/prioridade", json={"prioridade": "alta"})
        self.assertEqual(r.json["prioridade"], "alta")
        self.assertEqual(self.client.patch(f"/api/chamados/{id_}/prioridade", json={"prioridade": "x"}).status_code, 400)
        self.assertEqual(self.client.patch("/api/chamados/999/prioridade", json={"prioridade": "alta"}).status_code, 404)

    def test_exclui_chamado(self):
        id_ = self.criar().json["id"]
        self.criar(titulo="Fica")
        self.assertEqual(self.client.delete(f"/api/chamados/{id_}").status_code, 204)
        restantes = self.client.get("/api/chamados").json
        self.assertEqual([c["titulo"] for c in restantes], ["Fica"])
        self.assertEqual(self.client.delete(f"/api/chamados/{id_}").status_code, 404)

    def test_reabre_chamado_resolvido(self):
        id_ = self.criar().json["id"]
        self.client.patch(f"/api/chamados/{id_}/status", json={"status": "resolvido"})
        r = self.client.post(f"/api/chamados/{id_}/reabrir")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["status"], "aberto")

    def test_reabrir_so_vale_para_resolvido_e_existente(self):
        id_ = self.criar().json["id"]  # nasce "aberto"
        self.assertEqual(self.client.post(f"/api/chamados/{id_}/reabrir").status_code, 409)
        self.assertEqual(self.client.post("/api/chamados/999/reabrir").status_code, 404)

    def test_migra_banco_antigo_sem_prioridade(self):
        import sqlite3
        conn = sqlite3.connect(self.tmp.name)
        conn.execute("DROP TABLE chamados")
        conn.execute(
            "CREATE TABLE chamados (id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, "
            "descricao TEXT, solicitante TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'aberto', "
            "criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
        )
        conn.execute("INSERT INTO chamados (titulo, solicitante) VALUES ('antigo', 'Zé')")
        conn.commit()
        conn.close()
        init_db()
        self.assertEqual(self.client.get("/api/chamados").json[0]["prioridade"], "media")


if __name__ == "__main__":
    unittest.main()
