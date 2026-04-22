using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Security.Principal;
using System.Windows;
using WixSharp;
using WixSharp.CommonTasks;
using WixSharp.UI.Forms;
using WixSharp.UI.WPF;
using WixToolset.Dtf.WindowsInstaller;

namespace XXAR.Installer.Dialogs
{
    public partial class XXARProgressDialog : WpfDialog, IWpfDialog, IProgressDialog
    {
        private Model model;

        public XXARProgressDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            UpdateTitles(ManagedFormHost.Runtime.Session);
            model = new Model { Host = ManagedFormHost };
            DataContext = model;
            model.StartExecute();
        }

        public void UpdateTitles(ISession session)
        {
            if (session.IsUninstalling())
            {
                DialogTitleLabel.Text = "[ProgressDlgTitleRemoving]";
                DialogDescription.Text = "[ProgressDlgTextRemoving]";
            }
            else if (session.IsRepairing())
            {
                DialogTitleLabel.Text = "[ProgressDlgTextRepairing]";
                DialogDescription.Text = "[ProgressDlgTitleRepairing]";
            }
            else
            {
                DialogTitleLabel.Text = "[ProgressDlgTitleInstalling]";
                DialogDescription.Text = "[ProgressDlgTextInstalling]";
            }
            this.Localize();
        }

        public override MessageResult ProcessMessage(InstallMessage messageType, Record messageRecord,
            MessageButtons buttons, MessageIcon icon, MessageDefaultButton defaultButton)
            => model?.ProcessMessage(messageType, messageRecord) ?? MessageResult.None;

        public override void OnExecuteComplete() => model?.OnExecuteComplete();

        public override void OnProgress(int progressPercentage)
        {
            if (model != null) model.ProgressValue = progressPercentage;
        }

        private void Cancel_Click(object sender, RoutedEventArgs e) => model?.Cancel();

        private class Model : INotifyPropertyChanged
        {
            public ManagedForm Host;
            private ISession session => Host?.Runtime?.Session;
            private IManagedUIShell shell => Host?.Shell;

            private string currentAction;
            private int progressValue;
            private bool uacPromptActioned;

            public string CurrentAction
            {
                get => currentAction;
                set { currentAction = value; OnChanged(); }
            }

            public int ProgressValue
            {
                get => progressValue;
                set { progressValue = value; OnChanged(); }
            }

            public bool UacPromptIsVisible
                => !WindowsIdentity.GetCurrent().IsAdmin() && Uac.IsEnabled() && !uacPromptActioned;

            public string UacPrompt
            {
                get
                {
                    if (!Uac.IsEnabled()) return null;
                    var prompt = session?.Property("UAC_WARNING");
                    if (!string.IsNullOrEmpty(prompt)) return prompt;
                    return "Please wait for UAC prompt to appear. " +
                           "If it appears minimized then activate it from the taskbar.";
                }
            }

            public void StartExecute() => shell?.StartExecute();

            public void Cancel()
            {
                if (shell != null && shell.IsDemoMode) shell.GoNext();
                else shell?.Cancel();
            }

            public MessageResult ProcessMessage(InstallMessage messageType, Record messageRecord)
            {
                switch (messageType)
                {
                    case InstallMessage.InstallStart:
                    case InstallMessage.InstallEnd:
                        uacPromptActioned = true;
                        OnChanged(nameof(UacPromptIsVisible));
                        OnChanged(nameof(UacPrompt));
                        break;

                    case InstallMessage.ActionStart:
                        try
                        {
                            if (messageRecord != null && messageRecord.FieldCount >= 3)
                                CurrentAction = messageRecord[2]?.ToString();
                            else
                                CurrentAction = null;
                        }
                        catch
                        {
                            // intentionally swallowed — don't crash the installer on a malformed message
                        }
                        break;
                }
                return MessageResult.OK;
            }

            public void OnExecuteComplete()
            {
                CurrentAction = null;
                shell?.GoNext();
            }

            public event PropertyChangedEventHandler PropertyChanged;
            private void OnChanged([CallerMemberName] string name = null)
                => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
        }
    }
}
