-- NEXT 2026 | Correção isolada da limpeza de histórico.
-- Pode ser executada novamente sem apagar avaliações.
-- Execute SOMENTE no SQL Editor do projeto NEXT 2026 (iwfqmdsrourtdvrgiums).
-- Este arquivo INSTALA/CORRIGE a função. Ele NÃO a executa e NÃO apaga notas.

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
AS $$
DECLARE
    total_apagadas integer := 0;
BEGIN
    IF p_confirmacao IS DISTINCT FROM 'APAGAR NOTAS' THEN
        RAISE EXCEPTION 'Confirmação de exclusão ausente';
    END IF;

    -- A chave da API continua privada no Vercel. A RPC também confirma
    -- que o ID autenticado no aplicativo corresponde a um admin ativo.
    IF NOT EXISTS (
        SELECT 1
          FROM public.banca_usuarios
         WHERE id = p_admin AND papel = 'admin' AND ativo IS TRUE
    ) THEN
        RAISE EXCEPTION 'Acesso restrito à coordenação';
    END IF;

    IF p_equipe IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.banca_equipes WHERE id = p_equipe
    ) THEN
        RAISE EXCEPTION 'Equipe não encontrada';
    END IF;

    -- Um WHERE explícito evita o bloqueio de DELETE sem filtro.
    DELETE FROM public.banca_avaliacoes
     WHERE equipe_id IN (
         SELECT e.id FROM public.banca_equipes AS e
         WHERE p_equipe IS NULL OR e.id = p_equipe
     );

    GET DIAGNOSTICS total_apagadas = ROW_COUNT;

    -- No mesmo commit: se a auditoria falhar, a exclusão é revertida.
    INSERT INTO public.banca_auditoria(usuario_id,equipe_id,evento,detalhe)
    VALUES (
        p_admin, p_equipe, 'evaluation_history_cleared',
        'notas_apagadas=' || total_apagadas ||
        '; grupo=' || COALESCE(p_equipe::text, 'TODOS')
    );

    RETURN jsonb_build_object('apagadas', total_apagadas);
END;
$$;

REVOKE ALL ON FUNCTION public.banca_limpar_avaliacoes(bigint,integer,text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.banca_limpar_avaliacoes(bigint,integer,text)
    TO service_role;

-- Atualiza o cache das funções da API do Supabase/PostgREST.
NOTIFY pgrst, 'reload schema';
COMMIT;

-- Apenas conferência; nenhuma nota é apagada nesta consulta.
SELECT p.proname AS funcao, pg_get_function_identity_arguments(p.oid) AS argumentos
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public' AND p.proname = 'banca_limpar_avaliacoes';
