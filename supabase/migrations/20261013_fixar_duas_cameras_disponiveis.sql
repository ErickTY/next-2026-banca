-- NEXT 2026 | Duas câmeras disponibilizadas para TODAS as equipes.
-- Opcional: normaliza os registros antigos e aplica regra no banco.
-- Execute somente no Supabase do NEXT 2026 (iwfqmdsrourtdvrgiums).
-- Não modifica notas C1/C2/C3, observações, câmeras USADAS ou usuários.
BEGIN;

UPDATE public.banca_avaliacoes
SET cameras_disponiveis = 2
WHERE cameras_disponiveis <> 2;

ALTER TABLE public.banca_avaliacoes
  ALTER COLUMN cameras_disponiveis SET DEFAULT 2;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.banca_avaliacoes'::regclass
      AND conname = 'banca_avaliacoes_disponiveis_sempre_duas'
  ) THEN
    ALTER TABLE public.banca_avaliacoes
      ADD CONSTRAINT banca_avaliacoes_disponiveis_sempre_duas
      CHECK (cameras_disponiveis = 2);
  END IF;
END
$$;

COMMIT;

SELECT COUNT(*) AS avaliacoes_com_disponiveis_diferente_de_dois
FROM public.banca_avaliacoes
WHERE cameras_disponiveis <> 2;
