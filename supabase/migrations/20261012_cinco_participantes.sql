-- NEXT 2026: ajustar 3 autorizados (A1–A3) + 2 não cadastrados (D1–D2).
-- Atualiza somente a função de validação. Preserva usuários e avaliações anteriores, inclusive seu histórico A4.
-- Execute apenas uma vez no SQL Editor do projeto NEXT 2026, sem recriar o schema ou senhas.
begin;
create or replace function public.banca_salvar_avaliacao(
    p_equipe integer,
    p_usuario bigint,
    p_c1 integer,
    p_c2 integer,
    p_c3 integer,
    p_disponiveis integer,
    p_usadas integer,
    p_obs jsonb,
    p_notas text
) returns jsonb
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
    _id bigint;
    _item text;
    _valor text;
    _falha boolean := false;
begin
    -- Impede editar durante bloqueio e serializa com outras alterações do grupo.
    perform 1 from public.banca_equipes
      where id=p_equipe and bloqueado=false for update;
    if not found then
        raise exception 'Grupo não encontrado ou avaliação bloqueada';
    end if;
    if not exists(select 1 from public.banca_usuarios
                  where id=p_usuario and ativo=true and papel in ('judge','admin')) then
        raise exception 'Avaliador não autorizado';
    end if;
    if p_c1 not between 0 and 5 or p_c2 not between 0 and 5 or p_c3 not between 0 and 5 then
        raise exception 'Notas devem estar entre 0 e 5';
    end if;
    if p_usadas not between 1 and 2 or p_disponiveis not between 1 and 2 or p_usadas > p_disponiveis then
        raise exception 'Câmeras inválidas';
    end if;
    if jsonb_typeof(p_obs) is distinct from 'object' then
        raise exception 'Observações inválidas';
    end if;
    foreach _item in array array['A1','A2','A3','D1','D2'] loop
        _valor := p_obs->>_item;
        if (_item like 'A%' and _valor not in ('correto','erro','nao_testado')) or
           (_item like 'D%' and _valor not in ('alerta','falso_aceite','sem_leitura')) or
           _valor is null then
            raise exception 'Observação inválida: %',_item;
        end if;
        if _valor in ('erro','nao_testado','falso_aceite','sem_leitura') then
            _falha := true;
        end if;
    end loop;
    if (_falha or least(p_c1,p_c2,p_c3)<=2) and length(trim(coalesce(p_notas,'')))<10 then
        raise exception 'Justifique os erros e notas insuficientes';
    end if;
    insert into public.banca_avaliacoes(
        equipe_id,usuario_id,c1,c2,c3,cameras_disponiveis,cameras_usadas,
        observacoes,notes,updated_at
    ) values (
        p_equipe,p_usuario,p_c1,p_c2,p_c3,p_disponiveis,p_usadas,
        p_obs,left(coalesce(p_notas,''),3000),clock_timestamp()
    ) on conflict(equipe_id,usuario_id) do update
      set c1=excluded.c1,c2=excluded.c2,c3=excluded.c3,
          cameras_disponiveis=excluded.cameras_disponiveis,
          cameras_usadas=excluded.cameras_usadas,observacoes=excluded.observacoes,
          notes=excluded.notes,updated_at=excluded.updated_at
    returning id into _id;
    insert into public.banca_auditoria(usuario_id,equipe_id,evento,detalhe)
    values(p_usuario,p_equipe,'evaluation_saved',
           'c1='||p_c1||'; c2='||p_c2||'; c3='||p_c3||'; cameras='||p_usadas);
    return jsonb_build_object('id',_id,'total',p_c1+p_c2+p_c3);
end;
$$;
revoke all on function public.banca_salvar_avaliacao(integer,bigint,integer,integer,integer,integer,integer,jsonb,text) from public,anon,authenticated;
grant execute on function public.banca_salvar_avaliacao(integer,bigint,integer,integer,integer,integer,integer,jsonb,text) to service_role;
commit;

-- Dados anteriores não são removidos.