"""Controle de Chamados - API REST com Flask + SQLite."""
import sqlite3
from pathlib import Path

from flask import Flask, g, jsonify, request

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "chamados.db"

STATUS_VALIDOS = ("aberto", "em andamento", "resolvido")
PRIORIDADES_VALIDAS = ("baixa", "media", "alta")
PRIORIDADE_PADRAO = "media"

# Ordena do mais urgente para o menos urgente (alta -> media -> baixa)
ORDEM_PRIORIDADE = "CASE prioridade WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END"

app = Flask(__name__, static_folder="static", static_url_path="")


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
def get_db():
    """Abre (uma vez por requisição) a conexão com o SQLite."""
    if "db" not in g:
        g.db = sqlite3.connect(app.config.get("DATABASE", DB_PATH))
        g.db.row_factory = sqlite3.Row  # permite acessar colunas pelo nome
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    """Fecha a conexão ao fim de cada requisição."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Cria a tabela caso ainda não exista (os dados persistem no arquivo .db)."""
    with sqlite3.connect(app.config.get("DATABASE", DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chamados (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo      TEXT NOT NULL,
                descricao   TEXT,
                solicitante TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'aberto'
                            CHECK (status IN ('aberto', 'em andamento', 'resolvido')),
                criado_em   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                prioridade  TEXT NOT NULL DEFAULT 'media'
                            CHECK (prioridade IN ('baixa', 'media', 'alta'))
            )
            """
        )
        # Migração: bancos criados antes do extra não têm a coluna "prioridade".
        colunas = [c[1] for c in conn.execute("PRAGMA table_info(chamados)")]
        if "prioridade" not in colunas:
            conn.execute(
                "ALTER TABLE chamados ADD COLUMN prioridade TEXT NOT NULL DEFAULT 'media' "
                "CHECK (prioridade IN ('baixa', 'media', 'alta'))"
            )


def erro(mensagem, codigo=400):
    return jsonify({"erro": mensagem}), codigo


# ---------------------------------------------------------------------------
# Rotas da API
# ---------------------------------------------------------------------------
@app.get("/api/chamados")
def listar_chamados():
    """Lista chamados. Filtros opcionais: ?status=... e ?prioridade=...

    O resultado vem ordenado por prioridade (alta primeiro) e, dentro dela,
    do mais recente para o mais antigo.
    """
    status = request.args.get("status")
    prioridade = request.args.get("prioridade")
    condicoes, params = [], []

    if status:
        if status not in STATUS_VALIDOS:
            return erro(f"Status inválido. Use: {', '.join(STATUS_VALIDOS)}")
        condicoes.append("status = ?")
        params.append(status)

    if prioridade:
        if prioridade not in PRIORIDADES_VALIDAS:
            return erro(f"Prioridade inválida. Use: {', '.join(PRIORIDADES_VALIDAS)}")
        condicoes.append("prioridade = ?")
        params.append(prioridade)

    sql = "SELECT * FROM chamados"
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += f" ORDER BY {ORDEM_PRIORIDADE}, id DESC"

    rows = get_db().execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/chamados")
def criar_chamado():
    """Cria um chamado. Título e solicitante são obrigatórios."""
    dados = request.get_json(silent=True) or {}
    titulo = (dados.get("titulo") or "").strip()
    solicitante = (dados.get("solicitante") or "").strip()
    descricao = (dados.get("descricao") or "").strip()
    prioridade = dados.get("prioridade") or PRIORIDADE_PADRAO

    if not titulo or not solicitante:
        return erro("Título e solicitante são obrigatórios.")
    if prioridade not in PRIORIDADES_VALIDAS:
        return erro(f"Prioridade inválida. Use: {', '.join(PRIORIDADES_VALIDAS)}")

    db = get_db()
    # O status não é enviado: o DEFAULT do banco garante "aberto".
    cursor = db.execute(
        "INSERT INTO chamados (titulo, descricao, solicitante, prioridade) VALUES (?, ?, ?, ?)",
        (titulo, descricao, solicitante, prioridade),
    )
    db.commit()
    novo = db.execute("SELECT * FROM chamados WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(dict(novo)), 201


@app.patch("/api/chamados/<int:chamado_id>/status")
def alterar_status(chamado_id):
    """Altera o status de um chamado."""
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in STATUS_VALIDOS:
        return erro(f"Status inválido. Use: {', '.join(STATUS_VALIDOS)}")

    db = get_db()
    cursor = db.execute("UPDATE chamados SET status = ? WHERE id = ?", (status, chamado_id))
    db.commit()
    if cursor.rowcount == 0:
        return erro("Chamado não encontrado.", 404)

    atualizado = db.execute("SELECT * FROM chamados WHERE id = ?", (chamado_id,)).fetchone()
    return jsonify(dict(atualizado))


@app.patch("/api/chamados/<int:chamado_id>/prioridade")
def alterar_prioridade(chamado_id):
    """Altera a prioridade de um chamado."""
    prioridade = (request.get_json(silent=True) or {}).get("prioridade")
    if prioridade not in PRIORIDADES_VALIDAS:
        return erro(f"Prioridade inválida. Use: {', '.join(PRIORIDADES_VALIDAS)}")

    db = get_db()
    cursor = db.execute(
        "UPDATE chamados SET prioridade = ? WHERE id = ?", (prioridade, chamado_id)
    )
    db.commit()
    if cursor.rowcount == 0:
        return erro("Chamado não encontrado.", 404)

    atualizado = db.execute("SELECT * FROM chamados WHERE id = ?", (chamado_id,)).fetchone()
    return jsonify(dict(atualizado))


@app.post("/api/chamados/<int:chamado_id>/reabrir")
def reabrir_chamado(chamado_id):
    """Reabre um chamado resolvido, devolvendo-o ao status 'aberto'."""
    db = get_db()
    chamado = db.execute("SELECT status FROM chamados WHERE id = ?", (chamado_id,)).fetchone()
    if chamado is None:
        return erro("Chamado não encontrado.", 404)
    if chamado["status"] != "resolvido":
        return erro("Só é possível reabrir chamados resolvidos.", 409)

    db.execute("UPDATE chamados SET status = 'aberto' WHERE id = ?", (chamado_id,))
    db.commit()
    atualizado = db.execute("SELECT * FROM chamados WHERE id = ?", (chamado_id,)).fetchone()
    return jsonify(dict(atualizado))


@app.delete("/api/chamados/<int:chamado_id>")
def excluir_chamado(chamado_id):
    """Exclui um chamado definitivamente."""
    db = get_db()
    cursor = db.execute("DELETE FROM chamados WHERE id = ?", (chamado_id,))
    db.commit()
    if cursor.rowcount == 0:
        return erro("Chamado não encontrado.", 404)
    return "", 204  # sucesso sem corpo de resposta


@app.get("/")
def index():
    """Serve a interface web."""
    return app.send_static_file("index.html")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
