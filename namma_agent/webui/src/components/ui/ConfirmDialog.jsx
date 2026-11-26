import Button from "./Button.jsx";
import Dialog from "./Dialog.jsx";

// The in-app confirm (window.confirm is a no-op inside pywebview). Cancel holds
// the initial focus, so Enter never confirms a destructive action (BUG-12).
export default function ConfirmDialog({
  message, confirmLabel = "Delete", title = "Are you sure?", destructive = true, onResolve,
}) {
  return (
    <Dialog size="sm" title={title} description={message} onClose={() => onResolve(false)}
            footer={(
              <>
                <Button variant="ghost" data-autofocus onClick={() => onResolve(false)}>Cancel</Button>
                <Button variant={destructive ? "danger" : "primary"} data-destructive={destructive || undefined}
                        onClick={() => onResolve(true)}>{confirmLabel}</Button>
              </>
            )} />
  );
}
