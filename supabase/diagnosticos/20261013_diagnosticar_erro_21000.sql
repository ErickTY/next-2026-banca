-- NEXT 2026 - DIAGNÓSTICO SOMENTE LEITURA do erro PostgreSQL 21000.
-- Execute no SQL Editor do projeto iwfqmdsrourtdvrgiums.
-- NÃO apaga notas. NÃO cria nem altera funções, usuários ou tabelas.
-- Copie o resultado para análise. Não inclua chaves ou senhas.

WITH rels AS (
  SELECT c.oid, c.relname, c.relkind
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
    AND c.relname IN ('banca_avaliacoes', 'banca_auditoria')
),
defs AS (
  SELECT
    'FUNCAO'::text AS componente,
    p.oid::regprocedure::text AS nome,
    left(pg_get_functiondef(p.oid), 12000) AS detalhe
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public' AND p.proname = 'banca_limpar_avaliacoes'
),
triggers AS (
  SELECT
    'GATILHO'::text AS componente,
    r.relname || '.' || t.tgname AS nome,
    pg_get_triggerdef(t.oid, true) ||
    E'\n--- FUNCAO DO GATILHO ---\n' ||
    left(pg_get_functiondef(t.tgfoid), 12000) AS detalhe
  FROM pg_trigger t
  JOIN rels r ON r.oid = t.tgrelid
  WHERE NOT t.tgisinternal
),
rules AS (
  SELECT
    'REGRA'::text AS componente,
    r.relname || '.' || w.rulename AS nome,
    pg_get_ruledef(w.oid, true) AS detalhe
  FROM pg_rewrite w
  JOIN rels r ON r.oid = w.ev_class
  WHERE w.rulename <> '_RETURN'
),
relations AS (
  SELECT
    'TABELA'::text AS componente,
    relname::text AS nome,
    CASE relkind WHEN 'r' THEN 'tabela comum'
                 WHEN 'p' THEN 'tabela particionada'
                 WHEN 'v' THEN 'view'
                 ELSE 'tipo ' || relkind::text END AS detalhe
  FROM rels
)
SELECT componente, nome, detalhe
FROM (
  SELECT * FROM defs
  UNION ALL SELECT * FROM triggers
  UNION ALL SELECT * FROM rules
  UNION ALL SELECT * FROM relations
) info
ORDER BY componente, nome;
