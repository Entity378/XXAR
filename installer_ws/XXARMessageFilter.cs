using System.Windows.Forms;
using WixSharp;
using WixToolset.Dtf.WindowsInstaller;

namespace XXAR.Installer
{
    // Replaces the message box WixSharp's UIShell shows for MSI errors, so error 1926 can be dropped.
    // Everything else keeps the stock behaviour.
    internal class XXARMessageFilter : IManagedDialog
    {
        // Windows Installer raises 1926 once per rollback backup when the install volume is not the Windows one.
        // It offers no way to skip those backups and the install still succeeds, so a modal box per file is pure noise.
        private const string FileSecurityErrorCode = "1926";

        public IManagedUIShell Shell { get; set; }

        public MessageResult ProcessMessage(InstallMessage messageType, Record messageRecord,
            MessageButtons buttons, MessageIcon icon, MessageDefaultButton defaultButton)
        {
            if (messageType == InstallMessage.Error && IsFileSecurityError(messageRecord))
                return MessageResult.OK;

            // The DTF enums map 1:1 onto the WinForms ones, so plain casts are enough.
            return (MessageResult)(int)MessageBox.Show(
                messageRecord?.ToString() ?? string.Empty,
                "XXAR Setup",
                (MessageBoxButtons)(int)buttons,
                (MessageBoxIcon)(int)icon);
        }

        private static bool IsFileSecurityError(Record record)
        {
            // Field 1 of an error record is the MSI error number; a malformed record must never crash the installer.
            try
            {
                return record != null
                    && record.FieldCount >= 1
                    && record[1]?.ToString() == FileSecurityErrorCode;
            }
            catch
            {
                return false;
            }
        }

        public void OnExecuteStarted() { }

        public void OnExecuteComplete() { }

        public void OnProgress(int progressPercentage) { }
    }
}
