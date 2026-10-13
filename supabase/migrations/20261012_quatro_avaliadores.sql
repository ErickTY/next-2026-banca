-- NEXT 2026: quatro avaliadores oficiais + coordenacao.
-- O quinto usuario deixa de autenticar, sem exclusao de notas, fotos ou auditoria.
BEGIN;
UPDATE public.banca_usuarios
SET ativo = false, falhas_login = 0, bloqueado_ate = NULL
WHERE username = 'avaliador05' AND papel = 'judge';
COMMIT;
SELECT username, nome_exibicao, ativo
FROM public.banca_usuarios
WHERE username IN ('avaliador01','avaliador02','avaliador03','avaliador04','avaliador05')
ORDER BY username;
