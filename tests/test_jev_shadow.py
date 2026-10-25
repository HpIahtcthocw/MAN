import json
import pytest
from guardian.jev_shadow import classify,LABELS


def test_missing_jev_credential_never_sends(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY',raising=False)
    with pytest.raises(ValueError,match='NOT_CONFIGURED'):classify('查余额',lambda *_:pytest.fail('network'))


@pytest.mark.parametrize('invalid',[None,'permission',float('nan'),True])
def test_jev_answer_is_validated_and_never_authorizes_money(monkeypatch,invalid):
    monkeypatch.setenv('TYPESAFE_API_KEY','test-only')
    result={'model':'jev-1.13.0','answers':{'intent':{'type':'choice','choice':'bills','confidence':.9,
        'probabilities':{k:1.0 if k=='bills' else 0.0 for k in LABELS}}}}
    if invalid is not None:result['answers']['intent']['confidence']=invalid
    class Response:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def read(self,_):return json.dumps(result).encode()
    def fetch(request,timeout):
        payload=json.loads(request.data)
        assert payload['model']=='jev-1.13.0' and list(payload['questions'])==['intent']
        assert 'test-only' not in request.full_url and timeout==15
        return Response()
    if invalid is not None:
        with pytest.raises(ValueError):classify('查余额',fetch)
    else:
        value=classify('查余额',fetch)
        assert value['intent']=='bills' and value['shadow_only'] and 'approved' not in value
