-- NEXT 2026 | Correção do erro 21000: DELETE requires a WHERE clause.
-- Execute no SQL Editor do projeto dedicado NEXT 2026: iwfqmdsrourtdvrgiums.
-- Este script APENAS substitui a função de limpeza; NÃO executa exclusões.
-- Preserva avaliações, usuários, cronômetros, fotografias e auditoria.
-- A limpeza só acontece posteriormente, no painel da coordenação, após confirmação.

BEGIN;

CREATE OR REPLACE FUNCTION public.banca_limpar_avaliacoes(
    p_admin bigint,
    p_equipe integer DEFAULT NULL,
    p_confirmacao text DEFAULT ''
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $func$
DECLARE
    total_apagadas integer := 0;
BEGIN
    IF p_confirmacao IS DISTINCT FROM 'APAGAR NOTAS' THEN
        RAISE EXCEPTION 'Confirmação de exclusão ausente';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.banca_usuarios
        WHERE id = p_admin AND papel = 'admin' AND ativo IS TRUE
    ) THEN
        RAISE EXCEPTION 'Acesso restrito à coordenação';
    END IF;

    IF p_equipe IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.banca_equipes WHERE id = p_equipe
    ) THEN
        RAISE EXCEPTION 'Equipe não encontrada';
    END IF;

    -- O Supabase deste projeto rejeita DELETE sem WHERE (SQLSTATE 21000).
    -- Mesmo com p_equipe=NULL (todos), mantemos um WHERE explícito que
    -- seleciona apenas avaliações pertencentes às equipes cadastradas.
    DELETE FROM public.banca_avaliacoes
     WHERE equipe_id IN (
         SELECT e.id
         FROM public.banca_equipes AS e
         WHERE p_equipe IS NULL OR e.id = p_equipe
     );

    GET DIAGNOSTICS total_apagadas = ROW_COUNT;

    -- Falha de auditoria reverte a exclusão inteira, na mesma transação.
    INSERT INTO public.banca_auditoria(usuario_id,equipe_id,evento,detalhe)
    VALUES (
        p_admin,
        p_equipe,
        'evaluation_history_cleared',
        'notas_apagadas=' || total_apagadas ||
        '; grupo=' || COALESCE(p_equipe::text, 'TODOS')
    );

    RETURN jsonb_build_object('apagadas', total_apagadas);
END;
$func$;

REVOKE ALL ON FUNCTION public.banca_limpar_avaliacoes(bigint,integer,text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.banca_limpar_avaliacoes(bigint,integer,text)
    TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verificação apenas de leitura: a função existe e tem filtro de exclusão.
SELECT
  p.proname AS funcao,
  POSITION('WHERE equipe_id IN' IN pg_get_functiondef(p.oid)) > 0 AS delete_com_filtro
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname='public' AND p.proname='banca_limpar_avaliacoes';
