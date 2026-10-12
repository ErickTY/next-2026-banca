# NEXT 2026 — Sistema de Avaliação da Banca

Aplicação web de uso interno para o **Challenge DATEN | Microsoft Smart AI Vision**, com avaliação independente de nove equipes, cronômetro sincronizado de cinco minutos, auditoria e exportação CSV.

## Deploy no Vercel

Este repositório é **independente**, com o projeto na raiz (`Root Directory: ./`, `Framework Preset: Flask`, branch `main`).

1. Conecte este repositório ao Vercel.
2. Defina as variáveis `DATABASE_URL` (PostgreSQL persistente, conexão TLS), `SECRET_KEY` (segredo aleatório longo), `ADMIN_USERNAME` (p.ex. `coordenacao`) e `ADMIN_PASSWORD` (senha forte).
3. Publique pelo Vercel e acesse `/health` para testar.
4. Antes do NEXT, teste o login dos avaliadores, a persistência das notas, o cronômetro entre dois dispositivos e a exportação CSV.

**Não use SQLite em produção no Vercel:** os dados não persistem no armazenamento efêmero das funções. Credenciais não devem ser publicadas no código. A conta admin só é criada na primeira inicialização do banco.

As notas representam **somente a etapa de arena**; não correspondem automaticamente ao ranking definitivo. Os nomes dos grupos 1 e 6 estão provisórios, pendentes de confirmação.

## Uso local

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///local.db
export SECRET_KEY=defina-uma-chave-de-desenvolvimento
export ADMIN_USERNAME=coordenacao
export ADMIN_PASSWORD=defina-uma-senha-de-desenvolvimento
python app.py
```

Abra http://127.0.0.1:5000. No PowerShell, troque `export VAR=valor` por `$env:VAR="valor"`.

## Recursos

- Nove grupos, posições A22–A27 e A37–A39
- Login individual, testes A1–A4 e D1–D2, três critérios de 0 a 5
- Cronômetros centralizados por grupo controlados pela coordenação
- Cadastro de avaliadores, bloqueio de fichas, exportação e trilha de auditoria
- Interface responsiva para celular e notebook

**Uso exclusivo da equipe avaliadora; não divulgar credenciais aos alunos.**
