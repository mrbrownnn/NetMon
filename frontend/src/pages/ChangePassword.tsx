import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Field, Notice, Panel, useMutation } from './operations';

export default function ChangePassword() {
  const mutation = useMutation();
  const [values, setValues] = useState({ current_password: '', new_password: '', confirm_password: '' });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (values.new_password !== values.confirm_password) {
      const confirm = event.currentTarget.elements.namedItem('confirm_password') as HTMLInputElement;
      confirm.setCustomValidity('Mật khẩu xác nhận không khớp.'); confirm.reportValidity(); return;
    }
    void mutation.run(() => api.post('/api/account/password', values), () => setValues({ current_password: '', new_password: '', confirm_password: '' }), 'Đã đổi mật khẩu.');
  }
  return <><div className="nm-page-head"><h1>Đổi mật khẩu</h1></div><Panel title="Mật khẩu tài khoản"><form onSubmit={submit}><Notice mutation={mutation} />{([['current_password', 'Mật khẩu hiện tại'], ['new_password', 'Mật khẩu mới'], ['confirm_password', 'Xác nhận mật khẩu mới']] as const).map(([name, label]) => <Field key={name} label={`${label} *`} name={name} error={mutation.error?.errors}><input className="form-control" id={name} name={name} type="password" autoComplete={name === 'current_password' ? 'current-password' : 'new-password'} required value={values[name]} onChange={event => { const confirm = event.target.form?.elements.namedItem('confirm_password'); if (confirm instanceof HTMLInputElement) confirm.setCustomValidity(''); setValues(previous => ({ ...previous, [name]: event.target.value })); }} /></Field>)}<div className="nm-form-actions"><button type="submit" className="btn btn-primary" disabled={mutation.pending}>{mutation.pending ? 'Đang lưu…' : 'Đổi mật khẩu'}</button><Link to="/" className="btn btn-link">Hủy</Link></div></form></Panel></>;
}
