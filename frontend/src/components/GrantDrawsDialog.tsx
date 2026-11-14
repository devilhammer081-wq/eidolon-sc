"use client";

import { useEffect, useState, type FormEvent } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { NumberInput } from "@/components/app/admin/NumberInput";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldTitle } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { grantUserDraws, type AdminDrawGrant, type AdminUserDetails } from "@/lib/adminUsers";
import { toFailure, type Failure } from "@/lib/failure";

const t = copy.admin.users.draws;

const COUNT_MAX = 1000;

/**
 * 给一位用户增加抽奖次数（GLOSSARY.md「抽奖」）：只用于补偿，次数直接加在用户现有的抽奖次数上，
 * 可以超过每天最多攒的上限。后台不显示用户现在有多少次，也不显示礼物；用户下次打开礼物页时看到新到的次数。
 * `user` 为 null 时对话框关着；成功后把后端返回的发放结果交给 `onGranted`。保存是表单提交，用 default。
 */
export function GrantDrawsDialog({
  user,
  onClose,
  onGranted,
}: {
  user: Pick<AdminUserDetails, "id" | "name"> | null;
  onClose: () => void;
  onGranted: (grant: AdminDrawGrant) => void;
}) {
  const [count, setCount] = useState<number | null>(1);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    if (!user) return;
    setCount(1);
    setFailure(null);
  }, [user]);

  const problem = count === null || !Number.isInteger(count) || count < 1 || count > COUNT_MAX;

  function close() {
    if (!busy) onClose();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!user || problem || count === null) return;
    setBusy(true);
    setFailure(null);
    try {
      onGranted(await grantUserDraws(user.id, count));
    } catch (e) {
      setFailure(toFailure(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={user !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{t.title(user?.name ?? "")}</DialogTitle>
            <DialogDescription>{t.hint}</DialogDescription>
          </DialogHeader>
          <Field data-invalid={problem || undefined}>
            <FieldTitle>{t.count}</FieldTitle>
            <NumberInput
              label={t.count}
              value={count}
              onChange={setCount}
              min={1}
              max={COUNT_MAX}
              isIntegerOnly
              isInvalid={problem}
            />
            <FieldDescription>{t.countHint}</FieldDescription>
            {problem && <FieldError>{t.countProblem}</FieldError>}
          </Field>
          {failure && <FailureNotice failure={failure} />}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={close} disabled={busy}>
              {copy.common.cancel}
            </Button>
            <Button type="submit" disabled={busy || problem}>
              {busy && <Spinner data-icon="inline-start" />}
              {t.confirm}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
