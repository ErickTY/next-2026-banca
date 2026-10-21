-- NEXT 2026 | Coordenador de Curso e notas do Pré-NEXT (/40)
-- Instalação não altera avaliações da arena nem senhas atuais.
BEGIN;
ALTER TABLE public.banca_usuarios
  DROP CONSTRAINT IF EXISTS banca_usuarios_papel_check;
ALTER TABLE public.banca_usuarios
  ADD CONSTRAINT banca_usuarios_papel_check
  CHECK (papel IN ('admin','judge','course_coordinator'));

CREATE TABLE IF NOT EXISTS public.banca_prenext (
  equipe_id integer PRIMARY KEY REFERENCES public.banca_equipes(id),
  pontos numeric(5,2) NOT NULL CHECK (pontos >= 0 AND pontos <= 40),
  atualizado_em timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.banca_prenext ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.banca_prenext FROM PUBLIC,anon,authenticated;
GRANT SELECT, INSERT, UPDATE ON public.banca_prenext TO service_role;

-- Pontuações cumulativas do Pré-NEXT registradas na etapa classificatória.
-- A coordenação pode revisar/ajustar no painel; execução repetida não sobrescreve.
INSERT INTO public.banca_prenext(equipe_id,pontos) VALUES
(1,36),(2,34),(3,32),(4,31),(5,27),(6,26),(7,23),(8,23),(9,20)
ON CONFLICT(equipe_id) DO NOTHING;
NOTIFY pgrst, 'reload schema';
COMMIT;