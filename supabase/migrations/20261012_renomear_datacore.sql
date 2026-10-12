-- NEXT 2026: atualização segura no banco já instalado.
-- Preserva avaliações, usuários, cronômetros e auditoria.
BEGIN;
UPDATE public.banca_equipes
SET nome='Datacore', nome_pendente=false
WHERE id=1 AND nome IN ('GAVS-5', 'Datacore');
COMMIT;

SELECT id, nome, estande, nome_pendente
FROM public.banca_equipes
WHERE id=1;
