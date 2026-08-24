import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  Plus,
  History,
  Settings,
  ShieldCheck,
  Bell,
  ChevronRight,
  CheckCircle2,
  Clock3,
  XCircle,
  Upload,
  FileText,
  ArrowUpRight,
  BrainCircuit,
  CircleAlert,
  LockKeyhole,
  SlidersHorizontal,
  Menu,
  X,
  LoaderCircle,
  Building2,
  ChevronDown,
  KeyRound,
  LogOut,
  UserRound,
  Users,
  CreditCard,
  BarChart3,
  ArrowRight,
} from "lucide-react";
import {
  analyzeCase,
  createTeamInvitation,
  getCase,
  getCases,
  getDashboardStats,
  getBillingPlan,
  getAnalytics,
  getNotifications,
  getTeamAuditLog,
  getTeamInvitations,
  getTeamMembers,
  markNotificationRead,
  removeTeamMember,
  revokeTeamInvitation,
  submitDecision,
  updateTeamMemberRole,
} from "./services/api";
import { AuthGate, useAuth } from "./auth";
import { supabase } from "./services/supabase";
import "./styles.css";
import "./table.css";
import "./phase2.css";
import "./responsive.css";
import "./landing.css";
const nav = [
    ["Dashboard", LayoutDashboard],
    ["New Case", Plus],
    ["Decision History", History],
    ["Settings", Settings],
  ],
  pretty = (x) => (x || "").replaceAll("_", " "),
  latest = (x) => (x?.length ? x[x.length - 1] : null),
  extractHumanDecision = (value) => {
    if (value && typeof value === "object" && !Array.isArray(value))
      return value;
    if (Array.isArray(value)) {
      let decision = value.find(
        (item) => item && typeof item === "object" && !Array.isArray(item),
      );
      return decision || null;
    }
    return null;
  };
const Badge = ({ children, tone }) => (
  <span
    className={`badge ${tone || String(children).toLowerCase().replaceAll(" ", "-")}`}
  >
    {children}
  </span>
);
const Loading = ({ children = "Loading…" }) => (
  <div className="loading-state">
    <LoaderCircle size={20} />
    {children}
  </div>
);
const Error = ({ children }) => <div className="form-error">{children}</div>;
const safeError = (error, fallback) => {
  let message = String(error?.message || "").toLowerCase();
  if (message.includes("sign in") || message.includes("authentication"))
    return "Please sign in to continue.";
  if (message.includes("permission") || message.includes("forbidden"))
    return "You don't have permission to do that.";
  return fallback;
};
function Sidebar({ page, setPage, open, setOpen, identity }) {
  let auth = useAuth();
  identity = identity || {
    role: auth.profile?.role || "requester",
    organization: auth.profile?.organizations?.name || "My DECIDAI Workspace",
  };
  let visible = nav.filter(
    ([name]) => !(identity.role === "reviewer" && name === "New Case"),
  );
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="brand">
        <div className="brand-mark">DA</div>
        <div>
          <strong>DECIDAI</strong>
          <small>Decision intelligence</small>
        </div>
        <button
          className="mobile-close"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
        >
          <X size={18} />
        </button>
      </div>
      <div className="workspace-card">
        <span>
          <Building2 size={15} />
          {identity.organization}
        </span>
        <b className={`role-badge ${identity.role}`}>{identity.role}</b>
      </div>
      <nav>
        {visible.map(([n, I]) => (
          <button
            key={n}
            className={page === n ? "active" : ""}
            onClick={() => {
              setPage(n);
              setOpen(false);
            }}
          >
            <I size={19} />
            <span>{n}</span>
          </button>
        ))}
      </nav>
      <div className="side-bottom">
        <ShieldCheck size={18} />
        Human-in-the-Loop AI
      </div>
    </aside>
  );
}
function NotificationsCenter({ openCase }) {
  let [open, setOpen] = useState(false),
    [items, setItems] = useState([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [marking, setMarking] = useState(false);
  let load = async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await getNotifications());
    } catch (e) {
      setError(safeError(e, "Notifications are temporarily unavailable. Please try again."));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, []);
  let unread = items.filter((item) => !item.read).length;
  let mark = async (item) => {
    if (item.read || marking) return;
    setMarking(true);
    setNotice("");
    try {
      await markNotificationRead(item.id);
      setItems((rows) =>
        rows.map((row) => (row.id === item.id ? { ...row, read: true } : row)),
      );
      setNotice("Notification marked as read.");
    } catch (e) {
      setError(safeError(e, "We couldn't update that notification. Please try again."));
    } finally { setMarking(false); }
  };
  let markAll = async () => {
    if (marking || !unread) return;
    setMarking(true);
    setNotice("");
    try {
      await Promise.all(
        items.filter((item) => !item.read).map((item) => markNotificationRead(item.id)),
      );
      setItems((rows) => rows.map((row) => ({ ...row, read: true })));
      setNotice("All notifications marked as read.");
    } catch (e) {
      setError(safeError(e, "We couldn't update your notifications. Please try again."));
    } finally { setMarking(false); }
  };
  let openItem = async (item) => {
    await mark(item);
    if (item.decision_case_id) {
      openCase(item.decision_case_id);
      setOpen(false);
    }
  };
  return (
    <div className="notifications">
      <button
        className="header-icon"
        onClick={() => setOpen((value) => !value)}
        aria-label="Notifications"
        aria-expanded={open}
      >
        <Bell size={19} />
        {unread > 0 && <i>{unread > 99 ? "99+" : unread}</i>}
      </button>
      {open && (
        <section className="notifications-panel" aria-label="Notifications">
          <div className="notifications-head">
            <div>
              <b>Notifications</b>
              <span>{unread ? `${unread} unread` : "All caught up"}</span>
            </div>
            <button className="text-button" disabled={!unread || marking} onClick={markAll}>
              Mark all read
            </button>
          </div>
          {loading ? (
            <div className="notification-state">
              <LoaderCircle size={16} />
              Loading notifications…
            </div>
          ) : error ? (
            <div className="notification-error">
              <span>{error}</span>
              <button className="text-button" onClick={load}>Retry</button>
            </div>
          ) : items.length ? (
            <div className="notification-list">
              {items.map((item) => (
                <button
                  key={item.id}
                  className={`notification-item ${item.read ? "read" : "unread"}`}
                  onClick={() => openItem(item)}
                >
                  <span className="notification-dot" />
                  <span>
                    <b>{item.title}</b>
                    <small>{item.body}</small>
                    <em>{inviteExpiry(item.created_at)}</em>
                  </span>
                  {item.decision_case_id && <ChevronRight size={16} />}
                </button>
              ))}
            </div>
          ) : (
            <div className="notification-state empty">
              <Bell size={19} />
              You're all caught up.
            </div>
          )}
          {notice && <div className="notification-notice" role="status">{notice}</div>}
        </section>
      )}
    </div>
  );
}
function Header({ setOpen, setPage, identity, openCase }) {
  let auth = useAuth();
  identity = identity || {
    name:
      auth.profile?.full_name ||
      auth.user?.user_metadata?.full_name ||
      auth.user?.email?.split("@")[0] ||
      "Workspace member",
    role: auth.profile?.role || "requester",
    organization: auth.profile?.organizations?.name || "My DECIDAI Workspace",
    email: auth.profile?.email || auth.user?.email || "",
  };
  let [menuOpen, setMenuOpen] = useState(false);
  let initials = identity.name
    .split(" ")
    .map((x) => x[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <header>
      <button
        className="menu"
        onClick={() => setOpen(true)}
        aria-label="Open navigation"
      >
        <Menu size={21} />
      </button>
      <div className="header-tag">
        <BrainCircuit size={18} />
        AI Advises. <b>Human Decides.</b>
      </div>
      <div className="header-right">
        <NotificationsCenter openCase={openCase} />
        <div className="user-menu">
          <button
            className="user-trigger"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="Open account menu"
            aria-expanded={menuOpen}
          >
            <div className="avatar">{initials}</div>
            <span className="user-trigger-copy">
              <b>{identity.name}</b>
              <small>{identity.role}</small>
            </span>
            <ChevronDown size={15} />
          </button>
          {menuOpen && (
            <div className="user-dropdown">
              <div className="user-summary">
                <div className="avatar">{initials}</div>
                <div>
                  <b>{identity.name}</b>
                  <span>{identity.email}</span>
                  <em className={`role-badge ${identity.role}`}>
                    {identity.role}
                  </em>
                </div>
              </div>
              <div className="user-workspace">
                <Building2 size={15} />
                <span>{identity.organization}</span>
              </div>
              <button
                onClick={() => {
                  setPage("Settings");
                  setMenuOpen(false);
                }}
              >
                <UserRound size={16} />
                Profile
              </button>
              <button
                onClick={() => {
                  setPage("Settings");
                  setMenuOpen(false);
                }}
              >
                <Settings size={16} />
                Settings
              </button>
              <button
                className="logout"
                onClick={() => supabase?.auth.signOut()}
              >
                <LogOut size={16} />
                Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
function Stat({ label, value, Icon, tone }) {
  return (
    <div className="stat-card">
      <div>
        <p>{label}</p>
        <h2>{value}</h2>
        <span className="trend">Live database total</span>
      </div>
      <div className={`stat-icon ${tone}`}>
        <Icon size={22} />
      </div>
    </div>
  );
}
function Table({ rows, history, onOpen }) {
  if (!rows.length)
    return (
      <p className="empty-copy table-empty">
        {history ? "No finalized decisions yet." : "No decision cases yet."}
      </p>
    );
  let cols = history
    ? [
        "Case ID",
        "Case",
        "AI Recommendation",
        "AI Confidence",
        "Human Decision",
        "Reviewer",
        "Date",
        "Outcome",
      ]
    : [
        "Case ID",
        "Case Title",
        "Category",
        "AI Recommendation",
        "Confidence",
        "Human Decision",
        "Status",
        "Action",
      ];
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {cols.map((x) => (
              <th key={x}>{x}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <CaseRow key={c.id} c={c} history={history} onOpen={onOpen} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
function CaseRow({ c, history, onOpen }) {
  let a = latest(c.ai_analyses),
    d = extractHumanDecision(c.human_decisions),
    outcome = d?.is_override ? (
      <Badge tone="override">Human Override</Badge>
    ) : (
      <Badge
        tone={
          c.status === "PENDING_HUMAN_REVIEW"
            ? "pending"
            : c.status.toLowerCase()
        }
      >
        {pretty(c.status)}
      </Badge>
    );
  if (history)
    return (
      <tr className="click-row" onClick={() => onOpen(c.id)}>
        <td className="case-id">{c.case_id}</td>
        <td>
          <strong>{c.title}</strong>
          <small className="subline">{c.category}</small>
        </td>
        <td>
          <Badge>{pretty(a?.recommendation || "Pending")}</Badge>
        </td>
        <td>{a ? `${a.confidence}%` : "—"}</td>
        <td>
          <Badge tone={d?.final_decision?.toLowerCase()}>
            {d ? pretty(d.final_decision) : "Pending"}
          </Badge>
        </td>
        <td>{d?.reviewer_name || "—"}</td>
        <td>{new Date(c.created_at).toLocaleDateString()}</td>
        <td>{outcome}</td>
      </tr>
    );
  return (
    <tr className="click-row" onClick={() => onOpen(c.id)}>
      <td className="case-id">{c.case_id}</td>
      <td>
        <strong>{c.title}</strong>
      </td>
      <td>{c.category}</td>
      <td>
        <Badge>{pretty(a?.recommendation || "Pending")}</Badge>
      </td>
      <td>{a ? `${a.confidence}%` : "—"}</td>
      <td>
        <Badge tone={d?.final_decision?.toLowerCase()}>
          {d ? pretty(d.final_decision) : "Pending"}
        </Badge>
      </td>
      <td>{outcome}</td>
      <td>
        <button
          className="link-button"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(c.id);
          }}
        >
          View Case <ChevronRight size={15} />
        </button>
      </td>
    </tr>
  );
}
function Dashboard({ setPage, openCase }) {
  let auth = useAuth(),
    canCreate = ["admin", "requester"].includes(auth.profile?.role),
    isAdmin = auth.profile?.role === "admin",
    [stats, setStats] = useState(),
    [rows, setRows] = useState(),
    [analytics, setAnalytics] = useState(),
    [error, setError] = useState("");
  let load = () => {
    setError("");
    setStats(undefined);
    setRows(undefined);
    setAnalytics(undefined);
    let requests = [getDashboardStats(), getCases()];
    if (isAdmin) requests.push(getAnalytics());
    Promise.all(requests)
      .then(([s, c, a]) => {
        setStats(s);
        setRows(c.slice(0, 5));
        setAnalytics(a);
      })
      .catch(() =>
        setError(
          "Decision records are temporarily unavailable. Please try again.",
        ),
      );
  };
  useEffect(() => {
    load();
  }, []);
  if (error) return <div className="page-state"><Error>{error}</Error><button className="secondary" onClick={load}>Retry</button></div>;
  if (!stats || !rows || (isAdmin && !analytics)) return <Loading>Loading dashboard…</Loading>;
  return (
    <>
      <section className="page-heading">
        <div>
          <span className="eyebrow">OVERVIEW</span>
          <h1>Decision Dashboard</h1>
          <p>
            Explainable AI decision intelligence with human final authority.
          </p>
        </div>
        {canCreate && (
          <button className="primary" onClick={() => setPage("New Case")}>
            <Plus size={18} />
            New Decision Case
          </button>
        )}
      </section>
      <div className="stats stats-five">
        <Stat
          label="Total Cases"
          value={stats.total_cases}
          Icon={FileText}
          tone="blue"
        />
        <Stat
          label="Pending Review"
          value={stats.pending_review}
          Icon={Clock3}
          tone="amber"
        />
        <Stat
          label="Approved"
          value={stats.approved}
          Icon={CheckCircle2}
          tone="green"
        />
        <Stat
          label="Rejected"
          value={stats.rejected}
          Icon={XCircle}
          tone="red"
        />
        <Stat
          label="Human Overrides"
          value={stats.human_overrides}
          Icon={SlidersHorizontal}
          tone="blue"
        />
      </div>
      <p className="auditability-copy">
        Human-led decisions recorded with full auditability
      </p>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h3>Recent Decision Cases</h3>
            <p>Latest cases requiring review or recently finalized.</p>
          </div>
          <button
            className="text-button"
            onClick={() => setPage("Decision History")}
          >
            View all <ArrowUpRight size={15} />
          </button>
        </div>
        {rows.length ? (
          <Table rows={rows} onOpen={openCase} />
        ) : (
          <div className="empty-state">
            <span>No cases have been created in this workspace yet.</span>
            {canCreate && (
              <button className="primary" onClick={() => setPage("New Case")}>
                Create First Case
              </button>
            )}
          </div>
        )}
      </section>
      {isAdmin && <AdminAnalytics analytics={analytics} />}
    </>
  );
}
function AdminAnalytics({ analytics }) {
  let overview = analytics.overview || {}, timeline = analytics.cases_over_time || [], outcomes = analytics.decisions_by_outcome || {}, comparisons = analytics.ai_recommendation_vs_human_decision || [];
  let maxCases = Math.max(1, ...timeline.map((item) => item.count || 0));
  let cards = [
    ["Total cases", overview.total_cases], ["Pending reviews", overview.pending_review], ["Approved", overview.approved], ["Rejected", overview.rejected], ["Human overrides", overview.human_overrides], ["AI analyses", overview.ai_analyses], ["Active team members", overview.team_members], ["Invitations sent", overview.invitations_sent], ["Approval rate", `${overview.approval_rate || 0}%`], ["Average AI confidence", `${overview.average_ai_confidence || 0}%`],
  ];
  return <section className="admin-analytics"><div className="admin-analytics-heading"><div><span className="eyebrow">ADMIN ANALYTICS</span><h2><BarChart3 size={19} />Workspace activity</h2><p>Organization-wide decision activity and usage.</p></div></div><div className="analytics-metric-grid">{cards.map(([label, value]) => <article key={label}><span>{label}</span><b>{value ?? 0}</b></article>)}</div>{!overview.total_cases ? <div className="empty-state analytics-empty"><BarChart3 size={22} /><span>No organization activity has been recorded yet.</span></div> : <div className="analytics-chart-grid"><section className="analytics-chart"><h3>Cases created over time</h3><div className="timeline-bars">{timeline.map((item) => <div key={item.date} title={`${item.date}: ${item.count} cases`}><i style={{height:`${Math.max(5, Math.round(((item.count || 0) / maxCases) * 100))}%`}} /><span>{item.date.slice(5)}</span></div>)}</div></section><section className="analytics-chart"><h3>Decisions by outcome</h3><div className="outcome-bars">{[["Approved", outcomes.APPROVED || 0, "approved"], ["Rejected", outcomes.REJECTED || 0, "rejected"]].map(([label, value, tone]) => <div key={label}><span>{label}</span><b>{value}</b><i className={tone} style={{width:`${Math.min(100, ((value / Math.max(1, (outcomes.APPROVED || 0) + (outcomes.REJECTED || 0))) * 100))}%`}} /></div>)}</div></section><section className="analytics-chart comparison-chart"><h3>AI recommendation vs human decision</h3>{comparisons.length ? <div className="comparison-list">{comparisons.map((item) => <div key={`${item.recommendation}-${item.decision}`}><span>{pretty(item.recommendation)} → {pretty(item.decision)}</span><b>{item.count}</b></div>)}</div> : <p>No finalized AI-assisted decisions yet.</p>}</section></div>}</section>;
}
function NewCase({ setPage, setData }) {
  let ref = useRef(),
    [file, setFile] = useState(),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  async function submit(e) {
    e.preventDefault();
    setError("");
    let fd = new FormData(e.currentTarget);
    if (!file) fd.delete("supporting_document");
    setLoading(true);
    try {
      setData({ ...(await analyzeCase(fd)), _justCreated: true });
      setPage("Case Analysis");
    } catch (x) {
      setError(safeError(x, "We couldn't create and analyze this case. Please try again."));
    } finally {
      setLoading(false);
    }
  }
  return (
    <>
      <section className="page-heading compact">
        <div>
          <span className="eyebrow">NEW REQUEST</span>
          <h1>Create Decision Case</h1>
          <p>Provide the case details for AI-assisted analysis.</p>
        </div>
      </section>
      <form className="form-grid" onSubmit={submit}>
        <section className="panel form-panel">
          <div className="panel-heading">
            <div>
              <h3>Case Information</h3>
              <p>Enter information needed to assess this request.</p>
            </div>
          </div>
          <div className="fields">
            <label>
              Case Title
              <input name="title" required />
            </label>
            <label>
              Category
              <select name="category" required defaultValue="">
                <option value="" disabled>
                  Select a category
                </option>
                {[
                  "Procurement",
                  "Expense Approval",
                  "Vendor Selection",
                  "Policy Exception",
                  "Other",
                ].map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
            <label>
              Request Amount
              <input name="amount" required placeholder="₹ 0.00" />
            </label>
            <label>
              Requester Name
              <input name="requester_name" required />
            </label>
            <label>
              Department
              <input name="department" required />
            </label>
            <label className="full">
              Description
              <textarea name="description" required />
            </label>
          </div>
        </section>
        <section className="panel form-panel">
          <div className="panel-heading">
            <div>
              <h3>Supporting Documents</h3>
              <p>Add relevant documentation or company policies.</p>
            </div>
          </div>
          <input
            ref={ref}
            name="supporting_document"
            type="file"
            accept=".pdf,.docx,.txt"
            hidden
            onChange={(e) => setFile(e.target.files[0])}
          />
          <button
            type="button"
            className={`upload-zone ${file ? "uploaded" : ""}`}
            onClick={() => ref.current.click()}
          >
            {file ? (
              <>
                <CheckCircle2 size={27} />
                <strong>{file.name}</strong>
                <span>Document ready for analysis</span>
              </>
            ) : (
              <>
                <div className="upload-icon">
                  <Upload size={22} />
                </div>
                <strong>Upload supporting document or company policy</strong>
                <span>PDF, DOCX, TXT · Maximum size: 10 MB</span>
                <em>Choose file</em>
              </>
            )}
          </button>
        </section>
        <div className="form-actions">
          {error && <Error>{error}</Error>}
          {loading && (
            <div className="loading-copy">
              <LoaderCircle size={17} />
              Analyzing and saving case…
            </div>
          )}
          <button
            className="secondary"
            type="button"
            disabled={loading}
            onClick={() => setPage("Dashboard")}
          >
            Cancel
          </button>
          <button className="primary" disabled={loading}>
            {loading ? "Analyzing case…" : "Analyze with AI"}
          </button>
        </div>
      </form>
    </>
  );
}
function Human({ data, onRecorded }) {
  let auth = useAuth(),
    a = data.analysis,
    existing =
      data.human_decision || extractHumanDecision(data.human_decisions),
    [choice, setChoice] = useState(""),
    [reason, setReason] = useState(""),
    [reviewer, setReviewer] = useState("Alex Morgan"),
    [confirm, setConfirm] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  if (!["admin", "reviewer"].includes(auth.profile?.role))
    return (
      <section className="human-panel">
        <span className="eyebrow">HUMAN FINAL AUTHORITY</span>
        <h2>Decision review</h2>
        <p>Only workspace admins and reviewers can submit a final decision.</p>
      </section>
    );
  if (existing)
    return (
      <section className="human-panel">
        {data._decisionRecorded && (
          <div className="selected-note" role="status">
            <CheckCircle2 size={16} /> Final decision submitted and added to the audit trail.
          </div>
        )}
        <span className="eyebrow">FINAL DECISION RECORDED</span>
        <h2>Human Decision: {pretty(existing.final_decision)}</h2>
        <p>
          <b>AI Recommendation:</b> {pretty(a.recommendation)}
        </p>
        {existing.is_override ? (
          <div className="override-alert">
            <b>Human Override</b>
            <br />
            The reviewer selected a different final outcome from the AI
            recommendation.
          </div>
        ) : (
          <p className="decision-note">
            Human decision recorded after AI-assisted review.
          </p>
        )}
        <p>
          <b>Reviewer:</b> {existing.reviewer_name}
        </p>
        <p>
          <b>Decision Reason:</b> {existing.decision_reason}
        </p>
        <p>
          <b>Timestamp:</b> {new Date(existing.created_at).toLocaleString()}
        </p>
      </section>
    );
  let flip =
    a.recommendation === "APPROVE"
      ? "REJECTED"
      : a.recommendation === "REJECT"
        ? "APPROVED"
        : null;
  async function save() {
    setError("");
    setLoading(true);
    try {
      await submitDecision(data.decision_case_id, {
        final_decision: choice,
        decision_reason: reason,
        reviewer_name: reviewer,
      });
      setConfirm(false);
      onRecorded(true);
    } catch (e) {
      setError(
        "Decision records are temporarily unavailable. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="human-panel">
      <span className="eyebrow">HUMAN FINAL AUTHORITY</span>
      <h2>Your Decision</h2>
      <p>AI can recommend. Only you can decide.</p>
      <div className="decision-buttons">
        <button
          type="button"
          className={choice === "APPROVED" ? "selected approve" : ""}
          onClick={() => setChoice("APPROVED")}
        >
          <CheckCircle2 size={19} />
          Approve
        </button>
        <button
          type="button"
          className={choice === "REJECTED" ? "selected reject" : ""}
          onClick={() => setChoice("REJECTED")}
        >
          <XCircle size={19} />
          Reject
        </button>
        {flip && (
          <button
            type="button"
            className={choice === flip ? "selected override" : ""}
            onClick={() => setChoice(flip)}
          >
            <SlidersHorizontal size={19} />
            Override AI Recommendation
          </button>
        )}
      </div>
      <label className="reason">
        Decision Reason
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Explain the reasoning behind your final decision..."
        />
      </label>
      <label className="reason">
        Reviewer Name
        <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
      </label>
      {error && <Error>{error}</Error>}
      <button
        className="primary"
        type="button"
        disabled={!choice || !reason.trim() || !reviewer.trim() || loading}
        onClick={() => setConfirm(true)}
      >
        Submit Final Decision
      </button>
      {confirm && (
        <div className="confirm-dialog">
          <h3>Confirm Final Decision</h3>
          <p>
            You are about to <b>{choice}</b> this case.
          </p>
          <p>
            AI recommendation: <b>{pretty(a.recommendation)}</b>
          </p>
          <p>Your decision will be recorded in the audit trail.</p>
          <div>
            <button className="secondary" onClick={() => setConfirm(false)}>
              Cancel
            </button>
            <button className="primary" disabled={loading} onClick={save}>
              Confirm Decision
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
function Detail({ title, children }) {
  return (
    <section className="panel detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}
function Audit({ events = [] }) {
  let description = (e) => {
    let d = e.details || {};
    if (e.event_type === "AI_ANALYSIS_COMPLETED" && d.recommendation)
      return `DECIDAI recommended ${pretty(d.recommendation)} with ${d.confidence}% analysis confidence.`;
    if (e.event_type === "HUMAN_DECISION_SUBMITTED" && d.final_decision)
      return `${e.actor_name || "A reviewer"} ${pretty(d.final_decision).toLowerCase()} the case.`;
    if (e.event_type === "HUMAN_OVERRIDE")
      return "The reviewer selected a different final outcome from the AI recommendation.";
    if (e.event_type === "CASE_CREATED")
      return "Human submitted the business case details.";
    return null;
  };
  return (
    <Detail title="Decision Audit Trail">
      <div className="audit-list">
        {events.length ? (
          events
            .sort((x, y) => new Date(x.created_at) - new Date(y.created_at))
            .map((e) => (
              <div className="audit-event" key={e.id}>
                <b>{pretty(e.event_type)}</b>
                {description(e) && <em>{description(e)}</em>}
                <span>
                  {e.actor_name || e.actor_type} ·{" "}
                  {new Date(e.created_at).toLocaleString()}
                </span>
              </div>
            ))
        ) : (
          <p>No activity has been recorded for this case yet.</p>
        )}
      </div>
    </Detail>
  );
}
function Analysis({ data, refresh }) {
  if (!data) return <Loading>Loading case analysis…</Loading>;
  if (data._loadError)
    return <div className="page-state"><Error>We couldn't load this case. Please try again.</Error><button className="secondary" onClick={refresh}>Retry</button></div>;
  let d = data.case || data,
    a = data.analysis || latest(data.ai_analyses) || {};
  let current = {
    ...data,
    decision_case_id: data.decision_case_id || data.id,
    case: d,
    analysis: a,
    human_decision:
      data.human_decision || extractHumanDecision(data.human_decisions),
  };
  return (
    <>
      <section className="page-heading compact">
        <div>
          <span className="eyebrow">CASE {data.case_id}</span>
          <h1>Case Analysis</h1>
          <p>{d.title}</p>
        </div>
        <Badge
          tone={
            data.status === "PENDING_HUMAN_REVIEW"
              ? "pending"
              : data.status?.toLowerCase()
          }
        >
          {pretty(data.status || "PENDING_HUMAN_REVIEW")}
        </Badge>
      </section>
      <section className="info-strip">
        {[
          ["Requester", d.requester_name],
          ["Department", d.department],
          ["Request Amount", d.amount],
          ["Category", d.category],
        ].map(([x, y]) => (
          <div key={x}>
            <span>{x}</span>
            <b>{y}</b>
          </div>
        ))}
      </section>
      {data._justCreated && (
        <section className="notice analysis-notice" role="status">
          <CheckCircle2 size={18} />
          <span><b>Case created and analyzed.</b> Review the AI recommendation below before recording a human decision.</span>
        </section>
      )}
      <div className="analysis-layout">
        <div className="analysis-main">
          <section className="ai-card">
            <div className="ai-top">
              <div>
                <span className="eyebrow blue-text">AI ANALYSIS</span>
                <h3>AI Recommendation</h3>
              </div>
              <BrainCircuit size={24} />
            </div>
            <div className="recommendation">
              <Badge
                tone={
                  a.recommendation === "APPROVE"
                    ? "approved"
                    : a.recommendation === "REJECT"
                      ? "rejected"
                      : "needs-review"
                }
              >
                {pretty(a.recommendation)}
              </Badge>
              <div>
                <span>AI Analysis Confidence</span>
                <strong>{a.confidence}%</strong>
              </div>
            </div>
            <div className="progress">
              <i style={{ width: `${a.confidence}%` }} />
            </div>
            <p>
              Confidence reflects evidence completeness and consistency; it is
              not a probability that the recommendation is correct.
            </p>
            <div className="ai-disclaimer">
              <CircleAlert size={17} />
              <b>AI Recommendation Only</b> — Final decision must be made by a
              human reviewer.
            </div>
          </section>
          <Detail title="AI Case Summary">
            <p>{a.summary}</p>
          </Detail>
          <Detail title="Why AI Suggested This">
            <p>{a.reasoning}</p>
          </Detail>
          <Detail title="Evidence">
            {a.evidence?.length ? (
              a.evidence.map((x, i) => (
                <p key={i}>
                  <b>{x.title}:</b> {x.detail} ({pretty(x.source)})
                </p>
              ))
            ) : (
              <p>No supporting policy evidence available.</p>
            )}
          </Detail>
          <Detail title="Risk Flags">
            {a.risk_flags?.length ? (
              a.risk_flags.map((x, i) => (
                <p key={i}>
                  <b>
                    {x.title} · {x.severity}:
                  </b>{" "}
                  {x.detail}
                </p>
              ))
            ) : (
              <p>No material risk flags were returned.</p>
            )}
          </Detail>
          <Detail title="Missing Information">
            {a.missing_information?.length ? (
              <ul className="detail-list">
                {a.missing_information.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            ) : (
              <p>No major information gaps detected.</p>
            )}
          </Detail>
          <Detail title="Human Review Focus">
            {a.human_review_focus?.length ? (
              <ul className="detail-list">
                {a.human_review_focus.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            ) : (
              <p>No additional review focus was returned.</p>
            )}
          </Detail>
          <Audit events={data.audit_logs || []} />
        </div>
        <Human data={current} onRecorded={refresh} />
      </div>
    </>
  );
}
function HistoryPage({ openCase }) {
  let [rows, setRows] = useState(),
    [error, setError] = useState("");
  let load = () => {
    setError("");
    setRows(undefined);
    getCases()
      .then(setRows)
      .catch(() =>
        setError(
          "Decision records are temporarily unavailable. Please try again.",
        ),
      );
  };
  useEffect(() => {
    load();
  }, []);
  return (
    <>
      <section className="page-heading compact">
        <div>
          <span className="eyebrow">AUDIT TRAIL</span>
          <h1>Decision History</h1>
          <p>A transparent record of AI advice and human outcomes.</p>
        </div>
      </section>
      <section className="notice">
        <ShieldCheck size={19} />
        <span>
          <b>Human accountability is preserved.</b> Overrides are clearly marked
          in the decision record.
        </span>
      </section>
      {error ? (
        <div className="page-state"><Error>{error}</Error><button className="secondary" onClick={load}>Retry</button></div>
      ) : !rows ? (
        <Loading>Loading decision history…</Loading>
      ) : (
        <section className="panel">
          <Table rows={rows} history onOpen={openCase} />
        </section>
      )}
    </>
  );
}
function SettingsPage() {
  let controls = [
    [
      "Human Approval Required",
      "Every AI recommendation requires explicit human approval.",
      LockKeyhole,
      "Enabled",
    ],
    [
      "Explainable AI",
      "Show evidence and clear reasoning alongside recommendations.",
      BrainCircuit,
      "Enabled",
    ],
    [
      "Evidence Traceability",
      "Keep evidence tied to submitted case details and documents.",
      FileText,
      "Enabled",
    ],
    [
      "Missing Information Detection",
      "Highlight information gaps for human review.",
      CircleAlert,
      "Enabled",
    ],
    [
      "Audit Trail",
      "Maintain a traceable record of advice and final outcomes.",
      History,
      "Enabled",
    ],
    [
      "Human Override",
      "Allow a reviewer to record a different final outcome.",
      SlidersHorizontal,
      "Enabled",
    ],
    [
      "Automatic AI Approval",
      "AI cannot finalize a business decision.",
      LockKeyhole,
      "Disabled",
    ],
  ];
  return (
    <section className="settings-list">
      <section className="page-heading compact">
        <div>
          <span className="eyebrow">RESPONSIBLE AI CONTROLS</span>
          <h1>Settings</h1>
          <p>
            DECIDAI is intentionally designed so AI cannot finalize a business
            decision.
          </p>
        </div>
      </section>
      {controls.map(([n, d, I, status]) => (
        <section className="setting-card" key={n}>
          <div className="setting-icon">
            <I size={20} />
          </div>
          <div>
            <h3>{n}</h3>
            <p>{d}</p>
          </div>
          <div
            className={`enabled ${status === "Disabled" ? "disabled-control" : ""}`}
          >
            <i />
            {status}
            {(n === "Human Approval Required" ||
              n === "Automatic AI Approval") && <small>Locked</small>}
          </div>
        </section>
      ))}
    </section>
  );
}
const invitationStatus = (value) =>
  String(value || "pending").replace(/^./, (letter) => letter.toUpperCase());
const inviteExpiry = (value) => {
  let date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString();
};
function TeamMembers({ identity }) {
  let admin = identity.role === "admin",
    [members, setMembers] = useState([]),
    [invitations, setInvitations] = useState([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [inviteOpen, setInviteOpen] = useState(false),
    [invite, setInvite] = useState({ email: "", role: "reviewer" }),
    [submitting, setSubmitting] = useState(false),
    [successUrl, setSuccessUrl] = useState(""),
    [revokeId, setRevokeId] = useState(""),
    [memberAction, setMemberAction] = useState(""),
    [removeCandidate, setRemoveCandidate] = useState(null);
  let load = async () => {
    setLoading(true);
    setError("");
    try {
      let loadedMembers = await getTeamMembers(),
        loadedInvitations = admin ? await getTeamInvitations() : [];
      setMembers(loadedMembers);
      setInvitations(loadedInvitations);
    } catch (e) {
      setError(safeError(e, "We couldn't load workspace members. Please try again."));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, [admin]);
  let submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      let result = await createTeamInvitation(invite);
      setInvitations((items) => [result.invitation, ...items]);
      setSuccessUrl(result.invite_url);
      setInvite({ email: "", role: "reviewer" });
    } catch (e) {
      setError(safeError(e, "We couldn't create that invitation. Please try again."));
    } finally {
      setSubmitting(false);
    }
  };
  let revoke = async (id) => {
    setRevokeId(id);
    setError("");
    try {
      await revokeTeamInvitation(id);
      setInvitations((items) =>
        items.filter((invitation) => invitation.id !== id),
      );
      setNotice("Invitation revoked. The recipient can no longer use the invite link.");
    } catch (e) {
      setError(safeError(e, "We couldn't revoke that invitation. Please try again."));
    } finally {
      setRevokeId("");
    }
  };
  let copy = async () => {
    try {
      await navigator.clipboard.writeText(successUrl);
    } catch {
      setError("The invite link is ready. Copy it manually from the field below.");
    }
  };
  let lastAdmin = (member) =>
    member.role === "admin" &&
    members.filter((item) => item.role === "admin").length === 1;
  let changeRole = async (member, role) => {
    if (role === member.role) return;
    setMemberAction(member.id);
    setError("");
    setNotice("");
    try {
      let updated = await updateTeamMemberRole(member.id, role);
      setMembers((items) =>
        items.map((item) =>
          item.id === member.id
            ? { ...item, role: updated.new_role || role }
            : item,
        ),
      );
      setNotice("Member role updated successfully.");
    } catch (e) {
      setError(safeError(e, "We couldn't update that member's role. Please try again."));
    } finally {
      setMemberAction("");
    }
  };
  let remove = async () => {
    if (!removeCandidate) return;
    setMemberAction(removeCandidate.id);
    setError("");
    setNotice("");
    try {
      await removeTeamMember(removeCandidate.id);
      setMembers((items) =>
        items.filter((item) => item.id !== removeCandidate.id),
      );
      setNotice("Member removed from this workspace.");
      setRemoveCandidate(null);
    } catch (e) {
      setError(safeError(e, "We couldn't remove that member. Please try again."));
    } finally {
      setMemberAction("");
    }
  };
  return (
    <div className="team-members">
      <div className="team-toolbar">
        <div className="team-note">
          <Users size={17} />
          <span>
            {admin
              ? "Invite colleagues to this workspace and manage pending invitations."
              : "Workspace membership is shown according to your access."}
          </span>
        </div>
        {admin && (
          <button
            className="primary"
            onClick={() => {
              setSuccessUrl("");
              setInviteOpen(true);
            }}
          >
            <Users size={17} />
            Invite Member
          </button>
        )}
      </div>
      {error && <div className="page-state"><Error>{error}</Error><button className="secondary" onClick={load}>Retry</button></div>}
      {notice && (
        <div className="member-success" role="status">
          <CheckCircle2 size={16} />
          {notice}
        </div>
      )}
      {loading ? (
        <Loading>Loading team members…</Loading>
      ) : (
        <>
          <div className="team-table-wrap">
            <h3>Organization members</h3>
            {members.length ? (
              <table className="team-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Status</th>
                    {admin && <th aria-label="Member actions" />}
                  </tr>
                </thead>
                <tbody>
                  {members.map((member) => {
                    let protectedAdmin = lastAdmin(member);
                    return (
                      <tr key={member.id || member.email}>
                        <td>
                          <b>
                            {member.full_name ||
                              member.email?.split("@")[0] ||
                              "Workspace member"}
                          </b>
                        </td>
                        <td>{member.email || "—"}</td>
                        <td>
                          {admin ? (
                            <select
                              className="member-role-select"
                              value={member.role}
                              disabled={
                                protectedAdmin || memberAction === member.id
                              }
                              onChange={(event) =>
                                changeRole(member, event.target.value)
                              }
                              aria-label={
                                "Role for " + (member.email || "member")
                              }
                            >
                              <option value="admin">Admin</option>
                              <option value="reviewer">Reviewer</option>
                              <option value="requester">Requester</option>
                            </select>
                          ) : (
                            <span className={"role-badge " + member.role}>
                              {member.role}
                            </span>
                          )}
                        </td>
                        <td>
                          <span className="member-status">
                            <i />
                            Active
                          </span>
                        </td>
                        {admin && (
                          <td>
                            {protectedAdmin ? (
                              <span className="member-protected">
                                Last admin
                              </span>
                            ) : (
                              <button
                                className="text-button danger-text"
                                disabled={memberAction === member.id}
                                onClick={() => setRemoveCandidate(member)}
                              >
                                {memberAction === member.id
                                  ? "Updating…"
                                  : "Remove"}
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="empty-copy">No workspace members are available to your account yet.</p>
            )}
          </div>
          {admin && (
            <div className="team-table-wrap invitation-list">
              <h3>Invitations</h3>
              {invitations.length ? (
                <table className="team-table">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Role</th>
                      <th>Status</th>
                      <th>Expires</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {invitations.map((invitation) => (
                      <tr key={invitation.id}>
                        <td>{invitation.email}</td>
                        <td>
                          <span className={"role-badge " + invitation.role}>
                            {invitation.role}
                          </span>
                        </td>
                        <td>
                          <span
                            className={"invite-status " + invitation.status}
                          >
                            {invitationStatus(invitation.status)}
                          </span>
                        </td>
                        <td>{inviteExpiry(invitation.expires_at)}</td>
                        <td>
                          {invitation.status === "pending" && (
                            <button
                              className="text-button danger-text"
                              disabled={revokeId === invitation.id}
                              onClick={() => revoke(invitation.id)}
                            >
                              {revokeId === invitation.id
                                ? "Revoking…"
                                : "Revoke"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="empty-state compact-empty">
                  <span>No invitations have been sent yet.</span>
                  <span>Invite a teammate when you are ready to add them to this workspace.</span>
                  <button className="primary" onClick={() => { setSuccessUrl(""); setInviteOpen(true); }}>Invite Member</button>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {inviteOpen && (
        <div className="invite-modal-backdrop" role="presentation">
          <section
            className="invite-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="invite-title"
          >
            <button
              className="modal-close"
              type="button"
              aria-label="Close invite dialog"
              onClick={() => setInviteOpen(false)}
            >
              <X size={18} />
            </button>
            <span className="eyebrow">TEAM MEMBERS</span>
            <h3 id="invite-title">Invite a member</h3>
            <p>
              They will join this workspace with the selected role after
              accepting the invitation.
            </p>
            {successUrl ? (
              <div className="invite-success">
                <CheckCircle2 size={19} />
                <div>
                  <b>Invite created</b>
                  <span>Copy this link to test the invitation manually.</span>
                  <div className="invite-url">
                    <input
                      value={successUrl}
                      readOnly
                      aria-label="Invite URL"
                    />
                    <button type="button" className="secondary" onClick={copy}>
                      Copy
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <form className="invite-form" onSubmit={submit}>
                <label>
                  Email
                  <input
                    type="email"
                    required
                    value={invite.email}
                    onChange={(event) =>
                      setInvite((value) => ({
                        ...value,
                        email: event.target.value,
                      }))
                    }
                    placeholder="colleague@company.com"
                  />
                </label>
                <label>
                  Role
                  <select
                    value={invite.role}
                    onChange={(event) =>
                      setInvite((value) => ({
                        ...value,
                        role: event.target.value,
                      }))
                    }
                  >
                    <option value="admin">Admin</option>
                    <option value="reviewer">Reviewer</option>
                    <option value="requester">Requester</option>
                  </select>
                </label>
                <div className="invite-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setInviteOpen(false)}
                  >
                    Cancel
                  </button>
                  <button className="primary" disabled={submitting}>
                    {submitting ? (
                      <>
                        <LoaderCircle size={16} />
                        Sending…
                      </>
                    ) : (
                      "Send Invite"
                    )}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}
      {removeCandidate && (
        <div className="invite-modal-backdrop" role="presentation">
          <section
            className="invite-modal member-confirm"
            role="dialog"
            aria-modal="true"
            aria-labelledby="remove-member-title"
          >
            <button
              className="modal-close"
              type="button"
              aria-label="Close removal dialog"
              onClick={() => setRemoveCandidate(null)}
            >
              <X size={18} />
            </button>
            <span className="eyebrow">TEAM MEMBERS</span>
            <h3 id="remove-member-title">Remove member?</h3>
            <p>
              {removeCandidate.full_name || removeCandidate.email} will lose
              access to this workspace. Their authentication account will not be
              deleted.
            </p>
            <div className="invite-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setRemoveCandidate(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary danger-primary"
                disabled={memberAction === removeCandidate.id}
                onClick={remove}
              >
                {memberAction === removeCandidate.id
                  ? "Removing…"
                  : "Remove Member"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
function TeamAuditLog() {
  let [events, setEvents] = useState(),
    [members, setMembers] = useState([]),
    [error, setError] = useState("");
  let load = () => {
    setError("");
    setEvents(undefined);
    Promise.all([getTeamAuditLog(), getTeamMembers()])
      .then(([auditRows, team]) => {
        setEvents(auditRows);
        setMembers(team);
      })
      .catch((e) => setError(safeError(e, "We couldn't load the team audit log. Please try again.")));
  };
  useEffect(() => {
    load();
  }, []);
  let names = Object.fromEntries(
    members.map((member) => [
      member.id,
      member.full_name || member.email || "Workspace member",
    ]),
  );
  let person = (id, fallback) =>
    names[id] || fallback + " · " + String(id || "unknown").slice(0, 8);
  if (error) return <div className="page-state"><Error>{error}</Error><button className="secondary" onClick={load}>Retry</button></div>;
  if (!events) return <Loading>Loading team activity…</Loading>;
  return (
    <div className="team-table-wrap team-audit-log">
      <div className="team-note">
        <History size={17} />
        <span>
          Permanent record of workspace member role and access changes.
        </span>
      </div>
      {events.length ? (
        <table className="team-table">
          <thead>
            <tr>
              <th>Event</th>
              <th>Actor</th>
              <th>Target member</th>
              <th>Old role</th>
              <th>New role</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => {
              let details = event.details || {},
                removed = event.event_type === "TEAM_MEMBER_REMOVED";
              return (
                <tr key={event.id}>
                  <td>
                    <span
                      className={
                        "invite-status " + (removed ? "expired" : "accepted")
                      }
                    >
                      {removed ? "Member removed" : "Role changed"}
                    </span>
                  </td>
                  <td>{person(event.actor_user_id, "Admin")}</td>
                  <td>
                    {person(
                      event.target_user_id,
                      removed ? "Former member" : "Member",
                    )}
                  </td>
                  <td>{details.old_role || "—"}</td>
                  <td>{details.new_role || "—"}</td>
                  <td>{inviteExpiry(event.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <div className="empty-state">
          <History size={22} />
          <span>No team activity yet.</span>
          <span>Role changes and member removals will appear here.</span>
        </div>
      )}
    </div>
  );
}
const planCards = [
  { name: "FREE", items: ["10 cases/month", "10 AI analyses/month", "2 team members", "5 invitations/month"] },
  { name: "PRO", items: ["100 cases/month", "100 AI analyses/month", "10 team members", "30 invitations/month"] },
  { name: "BUSINESS", items: ["Unlimited cases", "Unlimited AI analyses", "50 team members", "Unlimited invitations"] },
];
const usageLabels = { cases_created: "Cases", ai_analyses: "AI analyses", team_members: "Team members", invitations_sent: "Invitations" };
function BillingUsage() {
  let [billing, setBilling] = useState(), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  let load = async () => {
    setError("");
    setLoading(true);
    try { setBilling(await getBillingPlan()); } catch (e) { setError(safeError(e, "We couldn't load billing and usage details. Please try again.")); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  if (error) return <div className="billing-error"><Error>{error}</Error><button className="secondary" onClick={load}>Try again</button></div>;
  if (loading || !billing) return <Loading>Loading billing and usage…</Loading>;
  if (!billing.limits || !billing.current_usage || !billing.remaining_usage) return <div className="empty-state"><CreditCard size={22} /><span>Usage information is not available yet.</span><span>Check back after your workspace has recorded activity.</span></div>;
  return <div className="billing-usage">
    <div className="billing-plan-summary"><div><span className="eyebrow">CURRENT PLAN</span><h3>{billing.plan}</h3><p>Usage resets monthly for cases, AI analyses, and invitations.</p></div><span className={`billing-plan-badge ${String(billing.plan).toLowerCase()}`}>{billing.plan}</span></div>
    <div className="usage-grid">{Object.entries(usageLabels).map(([metric, label]) => {
      let used = billing.current_usage[metric] ?? 0, limit = billing.limits[metric], remaining = billing.remaining_usage[metric], unlimited = limit === null || limit === undefined, percent = unlimited ? 0 : Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
      return <article className="usage-card" key={metric}><div className="usage-card-head"><span>{label}</span><b>{unlimited ? "Unlimited" : `${used} / ${limit}`}</b></div>{!unlimited && <div className="usage-progress" aria-label={`${label}: ${used} of ${limit}`}><i style={{width:`${percent}%`}} /></div>}<small>{unlimited ? "Unlimited on this plan" : `${remaining} remaining`}</small></article>;
    })}</div>
    <section className="plan-options"><div className="plan-options-head"><div><span className="eyebrow">PLANS</span><h3>Choose the right capacity</h3></div><p className="billing-free-note">Paid plans are coming soon. DECIDAI is currently free to use.</p></div><div className="plan-card-grid">{planCards.map((plan) => <article className={`plan-card ${billing.plan === plan.name ? "current" : ""}`} key={plan.name}><div className="plan-card-title"><h4>{plan.name}</h4>{billing.plan === plan.name && <span>Current plan</span>}</div><ul>{plan.items.map((item) => <li key={item}><CheckCircle2 size={14} />{item}</li>)}</ul><button className="secondary" disabled>Coming Soon</button></article>)}</div></section>
  </div>;
}
function SaaSSettings({ identity }) {
  let [tab, setTab] = useState("Profile");
  let tabs =
    identity.role === "admin"
      ? [
          ["Profile", UserRound],
          ["Organization", Building2],
          ["Team Members", Users],
          ["Team Audit Log", History],
          ["Billing & Usage", CreditCard],
          ["Security", KeyRound],
        ]
      : [
          ["Profile", UserRound],
          ["Organization", Building2],
          ["Team Members", Users],
          ["Security", KeyRound],
        ];
  return (
    <section className="settings-shell">
      <section className="page-heading compact">
        <div>
          <span className="eyebrow">WORKSPACE SETTINGS</span>
          <h1>Settings</h1>
          <p>Manage your profile, workspace, and security preferences.</p>
        </div>
      </section>
      <div className="settings-layout">
        <nav className="settings-tabs" aria-label="Settings sections">
          {tabs.map(([name, Icon]) => (
            <button
              key={name}
              className={tab === name ? "active" : ""}
              onClick={() => setTab(name)}
            >
              <Icon size={17} />
              {name}
            </button>
          ))}
        </nav>
        <section className="settings-content">
          <div className="settings-card-head">
            <div>
              <span className="eyebrow">{tab.toUpperCase()}</span>
              <h2>{tab}</h2>
            </div>
          </div>
          {tab === "Profile" && (
            <div className="profile-setting">
              <div className="profile-avatar">{identity.initials}</div>
              <div className="profile-info">
                <h3>{identity.name}</h3>
                <p>{identity.email}</p>
                <span className={"role-badge " + identity.role}>
                  {identity.role}
                </span>
              </div>
              <button className="secondary" disabled>
                Profile editing coming soon
              </button>
            </div>
          )}
          {tab === "Organization" && (
            <div className="organization-setting">
              <div className="setting-icon">
                <Building2 size={21} />
              </div>
              <div>
                <h3>{identity.organization}</h3>
                <p>
                  Workspace slug: <code>{identity.slug || "workspace"}</code>
                </p>
                <span className={"role-badge " + identity.role}>
                  {identity.role}
                </span>
              </div>
              <div className="admin-state">
                {identity.role === "admin"
                  ? "Admin controls are available through trusted workspace management."
                  : "Only workspace administrators can edit organization details."}
              </div>
            </div>
          )}
          {tab === "Team Members" && <TeamMembers identity={identity} />}{" "}
          {tab === "Team Audit Log" && <TeamAuditLog />}{" "}
          {tab === "Billing & Usage" && <BillingUsage />}{" "}
          {tab === "Security" && (
            <div className="security-setting">
              <div className="setting-icon">
                <KeyRound size={21} />
              </div>
              <div>
                <h3>Password and sign-in</h3>
                <p>
                  Manage your password through the secure Supabase
                  authentication flow.
                </p>
                <button
                  className="primary"
                  onClick={() => location.assign("/forgot-password")}
                >
                  Change password
                </button>
              </div>
              <div className="session-note">
                <ShieldCheck size={17} />
                <span>
                  Your session is protected by Supabase Auth and bearer-token
                  API requests.
                </span>
              </div>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
const publicNavigate = (path) => {
  history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
};
function LandingPage() {
  const features = [
    [BrainCircuit, "Explainable AI recommendations", "Clear reasoning and evidence help teams understand each recommendation."],
    [ShieldCheck, "Human final authority", "AI advises; people remain responsible for every final decision."],
    [History, "Decision audit trail", "A transparent record of the case, advice, review, and outcome."],
    [Users, "Team roles & collaboration", "Invite the right people and assign clear workspace responsibilities."],
    [BarChart3, "Decision analytics", "See decision activity and workspace usage in one focused view."],
  ];
  const steps = ["Create decision case", "AI analyzes evidence", "Human reviews", "Human makes final decision", "Decision is audited"];
  return <main className="landing-page">
    <header className="landing-header">
      <button className="landing-brand" onClick={() => publicNavigate("/")} aria-label="DECIDAI home"><span>DA</span><b>DECIDAI</b></button>
      <nav aria-label="Public navigation"><button className="landing-sign-in" onClick={() => publicNavigate("/login")}>Sign In</button><button className="landing-start" onClick={() => publicNavigate("/signup")}>Get Started <ArrowRight size={16} /></button></nav>
    </header>
    <section className="landing-hero">
      <span className="landing-kicker">HUMAN-IN-THE-LOOP AI</span>
      <h1>AI Advises.<br /><em>Human Decides.</em></h1>
      <p>DECIDAI helps teams make accountable, explainable business decisions with AI assistance and human final authority.</p>
      <div className="landing-actions"><button className="landing-start" onClick={() => publicNavigate("/signup")}>Get Started <ArrowRight size={17} /></button><button className="landing-demo-link" onClick={() => publicNavigate("/login")}>Sign In</button></div>
      <div className="landing-principle"><ShieldCheck size={18} /><span><b>Responsible by design.</b> AI recommends; humans make final decisions.</span></div>
    </section>
    <section className="landing-section" aria-labelledby="features-heading">
      <div className="landing-section-heading"><span className="landing-kicker">BUILT FOR ACCOUNTABLE DECISIONS</span><h2 id="features-heading">Clarity at every step</h2><p>Everything your team needs to move from a request to a well-documented decision.</p></div>
      <div className="landing-feature-grid">{features.map(([Icon, title, copy]) => <article key={title}><span><Icon size={20} /></span><h3>{title}</h3><p>{copy}</p></article>)}</div>
    </section>
    <section className="landing-section landing-how" aria-labelledby="how-heading">
      <div className="landing-section-heading"><span className="landing-kicker">HOW IT WORKS</span><h2 id="how-heading">Human judgment stays in control</h2></div>
      <ol>{steps.map((step, index) => <li key={step}><b>{String(index + 1).padStart(2, "0")}</b><span>{step}</span></li>)}</ol>
    </section>
    <section className="landing-responsible" aria-labelledby="responsible-heading"><div><span className="landing-kicker">RESPONSIBLE AI</span><h2 id="responsible-heading">AI recommends; humans make final decisions.</h2><p>DECIDAI keeps human oversight, reasoning, and accountability at the center of every workflow.</p></div><div className="landing-free-note">DECIDAI is currently free to use.<br />Paid plans are coming soon.</div></section>
    <footer className="landing-footer"><div><b>DECIDAI</b><span>AI Advises. Human Decides.</span></div><div><span>Privacy</span><span>Terms</span></div></footer>
  </main>;
}
function NotFoundPage({ authenticated = false }) {
  return <main className="not-found-page"><div className="not-found-card"><span className="landing-kicker">404</span><h1>Page not found</h1><p>The page you requested is not available.</p><button className="landing-start" onClick={() => { if (authenticated) location.assign("/"); else publicNavigate("/"); }}>{authenticated ? "Back to Dashboard" : "Back to Home"}<ArrowRight size={16} /></button></div></main>;
}
function SessionRoute() {
  return ["/", "", "/login", "/signup", "/forgot-password", "/reset-password"].includes(location.pathname) ? <App /> : <NotFoundPage authenticated />;
}
function RootRouter() {
  let [ready, setReady] = useState(false), [hasSession, setHasSession] = useState(false), [path, setPath] = useState(location.pathname);
  useEffect(() => {
    let mounted = true;
    let updatePath = () => setPath(location.pathname);
    addEventListener("popstate", updatePath);
    if (!supabase) { setReady(true); return () => removeEventListener("popstate", updatePath); }
    supabase.auth.getSession().then(({ data }) => { if (mounted) { setHasSession(Boolean(data.session)); setReady(true); } });
    let { data: { subscription } } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (mounted) setHasSession(Boolean(nextSession));
    });
    return () => { mounted = false; subscription.unsubscribe(); removeEventListener("popstate", updatePath); };
  }, []);
  if (!ready) return <Loading>Loading DECIDAI…</Loading>;
  if (!hasSession && (path === "/" || path === "")) return <LandingPage />;
  if (!hasSession && !["/login", "/signup", "/forgot-password", "/reset-password"].includes(path)) return <NotFoundPage />;
  return <AuthGate><SessionRoute /></AuthGate>;
}
function App() {
  let auth = useAuth(),
    role = auth.profile?.role || "requester",
    name =
      auth.profile?.full_name ||
      auth.user?.user_metadata?.full_name ||
      auth.user?.email?.split("@")[0] ||
      "Workspace member",
    identity = {
      role,
      name,
      organization: auth.profile?.organizations?.name || "My DECIDAI Workspace",
      email: auth.profile?.email || auth.user?.email || "",
      slug: auth.profile?.organizations?.slug || "",
      initials: name
        .split(" ")
        .map((x) => x[0])
        .join("")
        .slice(0, 2)
        .toUpperCase(),
    };
  let [page, setPage] = useState("Dashboard"),
    [open, setOpen] = useState(false),
    [data, setData] = useState(null);
  async function openCase(id) {
    try {
      setData(await getCase(id));
      setPage("Case Analysis");
    } catch {
      setData({ id, _loadError: true });
      setPage("Case Analysis");
    }
  }
  async function refresh(decisionRecorded = false) {
    try {
      let updated = await getCase(data.id || data.decision_case_id);
      setData({ ...updated, _decisionRecorded: decisionRecorded });
    } catch {
      setData({ id: data.id || data.decision_case_id, _loadError: true });
    }
  }
  let content =
    page === "Dashboard" ? (
      <Dashboard setPage={setPage} openCase={openCase} />
    ) : page === "New Case" ? (
      <NewCase setPage={setPage} setData={setData} />
    ) : page === "Case Analysis" ? (
      <Analysis data={data} refresh={refresh} />
    ) : page === "Decision History" ? (
      <HistoryPage openCase={openCase} />
    ) : (
      <SaaSSettings identity={identity} />
    );
  return (
    <div className={`app role-${role}`}>
      <Sidebar {...{ page, setPage, open, setOpen, identity }} />
      {open && (
        <button
          className="nav-scrim"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
        />
      )}
      <main>
        <Header {...{ setOpen, setPage, identity, openCase }} />
        <div className="content">
          {content}
          <footer>
            AI provides insights. Humans remain accountable for final decisions.
          </footer>
        </div>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")).render(
  <RootRouter />,
);
