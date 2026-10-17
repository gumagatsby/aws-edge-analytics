"""Generate the .drawio diagrams for this repo. Usage: python3 drawio_build.py <output dir>"""
import sys
from html import escape

OUTDIR = sys.argv[1]

C = {"storage": "#7AA116", "integration": "#E7157B", "compute": "#ED7100", "database": "#C925D1",
     "analytics": "#8C4FFF", "management": "#E7157B", "security": "#DD344C", "cost": "#7AA116"}
INK = "#232F3E"
EDGE = "#545B64"
RED = "#D13212"


class Doc:
    def __init__(self, name, w, h):
        self.name, self.w, self.h = name, w, h
        self.cells = []
        self.n = 2
        self.org = {"1": (0, 0)}  # absolute origin of each container; all coordinates passed in are absolute

    def _id(self):
        self.n += 1
        return f"c{self.n}"

    def add(self, value, style, x, y, w, h, parent="1", vertex=True):
        i = self._id()
        value = value.replace("\n", "<br>")
        self.org[i] = (x, y)
        px, py = self.org[parent]
        x, y = x - px, y - py
        self.cells.append(
            f'<mxCell id="{i}" value="{escape(value)}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return i

    def group(self, label, kind, x, y, w, h, parent="1", fs=12):
        styles = {
            "cloud": f"grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor={INK};fontColor={INK};dashed=0;",
            "region": "grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fontColor=#147EBA;dashed=1;",
            "account": "grIcon=mxgraph.aws4.group_account;strokeColor=#CD2264;fontColor=#CD2264;dashed=0;",
            "office": f"grIcon=mxgraph.aws4.group_corporate_data_center;strokeColor=#7D8998;fontColor={INK};dashed=0;",
            "vpc": "grIcon=mxgraph.aws4.group_vpc;strokeColor=#8C4FFF;fontColor=#8C4FFF;dashed=0;",
            "vpc_off": "grIcon=mxgraph.aws4.group_vpc;strokeColor=#8C4FFF;fontColor=#8C4FFF;dashed=1;",
            "public": "grIcon=mxgraph.aws4.group_security_group;strokeColor=#7AA116;fontColor=#248814;dashed=0;",
            "private": "grIcon=mxgraph.aws4.group_security_group;strokeColor=#00A4A6;fontColor=#147EBA;dashed=0;",
        }
        st = ("points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=%d;fontStyle=1;"
              "container=1;pointerEvents=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;"
              "fillColor=none;verticalAlign=top;align=left;spacingLeft=30;" % fs) + styles[kind]
        return self.add(label, st, x, y, w, h, parent)

    def box(self, label, x, y, w, h, parent="1", color="#879196", fs=12):
        st = (f"fillColor=none;strokeColor={color};dashed=1;verticalAlign=top;fontStyle=1;fontColor={color};"
              f"whiteSpace=wrap;html=1;align=left;spacingLeft=10;spacingTop=4;fontSize={fs};rounded=1;arcSize=3;container=1;collapsible=0;")
        return self.add(label, st, x, y, w, h, parent)

    @staticmethod
    def lab(pos):
        return {"below": "verticalLabelPosition=bottom;verticalAlign=top;align=center;",
                "above": "verticalLabelPosition=top;verticalAlign=bottom;align=center;",
                "right": "labelPosition=right;verticalLabelPosition=middle;align=left;verticalAlign=middle;spacingLeft=4;",
                "left": "labelPosition=left;verticalLabelPosition=middle;align=right;verticalAlign=middle;spacingRight=4;"}[pos]

    def res(self, label, icon, cat, x, y, parent="1", s=64, fs=12, pos="below"):
        st = (f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;fillColor={C[cat]};strokeColor=#ffffff;"
              f"dashed=0;html=1;fontSize={fs};" + self.lab(pos) +
              f"aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{icon};")
        return self.add(label, st, x, y, s, s, parent)

    def shape(self, label, shp, color, x, y, w=52, h=52, parent="1", fs=12, pos="below"):
        st = (f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;fillColor={color};strokeColor=none;"
              f"dashed=0;html=1;fontSize={fs};" + self.lab(pos) +
              f"aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.{shp};")
        return self.add(label, st, x, y, w, h, parent)

    def text(self, label, x, y, w, h, fs=12, bold=False, color=INK, align="left", parent="1"):
        st = (f"text;html=1;strokeColor=none;fillColor=none;align={align};verticalAlign=top;whiteSpace=wrap;"
              f"fontSize={fs};fontColor={color};fontStyle={1 if bold else 0};")
        return self.add(label, st, x, y, w, h, parent)

    def badge(self, n, x, y, parent="1", d=24, fs=12):
        st = (f"ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor={INK};strokeColor=none;fontColor=#FFFFFF;"
              f"fontStyle=1;fontSize={fs};")
        return self.add(str(n), st, x, y, d, d, parent)

    def _raw(self, html, st, x, y, w, h):
        i = self._id()
        self.org[i] = (x, y)
        self.cells.append(f'<mxCell id="{i}" value="{escape(html)}" style="{st}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return i

    @staticmethod
    def _label(title, tech, desc, fs):
        return (f"<b>{escape(title)}</b><br><span style='color:#545B64'>[{escape(tech)}]</span>"
                + (f"<br><span style='font-size:{fs - 1}px'>{escape(desc)}</span>" if desc else ""))

    def node(self, title, tech, desc, x, y, w=210, h=96, stroke=INK, dashed=False, fs=12):
        """C4 container: name, [technology], one-line purpose. White fill, 1px border."""
        st = (f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={stroke};strokeWidth=1;"
              f"fontColor={INK};fontSize={fs};verticalAlign=middle;spacing=8;" + ("dashed=1;" if dashed else ""))
        return self._raw(self._label(title, tech, desc, fs), st, x, y, w, h)

    def db(self, title, tech, desc, x, y, w=170, h=100, fs=12):
        st = (f"shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=12;fillColor=#FFFFFF;strokeColor={INK};"
              f"strokeWidth=1;fontColor={INK};fontSize={fs};")
        return self._raw(self._label(title, tech, desc, fs), st, x, y, w, h)

    def person(self, label, x, y, fs=12):
        st = (f"shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;outlineConnect=0;"
              f"fillColor=#FFFFFF;strokeColor={INK};fontColor={INK};fontSize={fs};")
        return self.add(label, st, x, y, 30, 56)

    def boundary(self, label, x, y, w, h):
        st = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#879196;dashed=1;dashPattern=8 4;"
              "verticalAlign=bottom;align=left;spacingLeft=10;spacingBottom=6;fontColor=#545B64;fontSize=12;fontStyle=1;")
        return self.add(label, st, x, y, w, h)

    def edge(self, src, dst, label="", color=EDGE, dashed=False, w=1.5, ex=None, ey=None, nx=None, ny=None, fs=11, via=None, both=False):
        i = self._id()
        st = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor={color};"
              + ("startArrow=block;startFill=1;" if both else "")
              + f"strokeWidth={w};fontSize={fs};fontColor={INK};labelBackgroundColor=#FFFFFF;"
              + ("dashed=1;dashPattern=6 4;" if dashed else ""))
        if ex is not None: st += f"exitX={ex};exitY={ey};exitDx=0;exitDy=0;"
        if nx is not None: st += f"entryX={nx};entryY={ny};entryDx=0;entryDy=0;"
        self.cells.append(
            f'<mxCell id="{i}" value="{escape(label.replace(chr(10), "<br>"))}" style="{st}" edge="1" parent="1" source="{src}" target="{dst}">'
            f'<mxGeometry relative="1" as="geometry">'
            + ('<Array as="points">' + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in via) + '</Array>' if via else "")
            + '</mxGeometry></mxCell>')
        return i

    def line(self, x1, y1, x2, y2, label="", dashed=False, color=EDGE, arrow=True, fs=11):
        i = self._id()
        st = (f"html=1;endArrow={'block' if arrow else 'none'};endFill=1;strokeColor={color};strokeWidth=1.5;fontSize={fs};"
              f"fontColor={INK};labelBackgroundColor=#FFFFFF;" + ("dashed=1;dashPattern=6 4;" if dashed else ""))
        self.cells.append(
            f'<mxCell id="{i}" value="{escape(label)}" style="{st}" edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/>'
            f'<mxPoint x="{x2}" y="{y2}" as="targetPoint"/></mxGeometry></mxCell>')

    def xml(self):
        return (f'<mxfile host="drawio"><diagram name="{escape(self.name)}">'
                f'<mxGraphModel dx="0" dy="0" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
                f'fold="1" page="1" pageScale="1" pageWidth="{self.w}" pageHeight="{self.h}" background="#FFFFFF" math="0" shadow="0">'
                '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
                + "".join(self.cells) + "</root></mxGraphModel></diagram></mxfile>")


GREY = "#879196"
SUB = "#545B64"

# =====================================================================
# 1. Architecture
# =====================================================================
d = Doc("Edge analytics: architecture", 1760, 1080)
d.add("", "rounded=0;fillColor=#FFFFFF;strokeColor=none;", 0, 0, 1760, 1080)
d.text("Edge analytics on AWS", 30, 20, 900, 34, fs=24, bold=True)
d.text("CloudFront logs every request; a daily pipeline turns them into cost, speed, experiment and bot reports",
       30, 56, 1300, 22, fs=14, color=SUB)

visitors = d.shape("Visitors\nworldwide", "users", INK, 50, 214, 60, 60)
gh = d.shape("GitHub Actions", "users", INK, 50, 904, 60, 60)
analysts = d.shape("Analysts and\ndata engineers", "users", INK, 1660, 680, 60, 60)

cloud = d.group("AWS Cloud", "cloud", 170, 100, 1450, 930)
edge = d.box("Global (edge)", 200, 140, 330, 560, parent=cloud)
cf = d.res("CloudFront\none distribution", "cloudfront", "analytics", 330, 210, parent=edge)
d.text("viewer-request function:\nA/B group from a hash of IP and\nuser agent, tracking parameters\nstripped before the cache lookup\n\n"
       "viewer-response function:\nA/B cookie, security headers",
       225, 330, 290, 150, fs=11, parent=edge)
d.text("Standard logging v2 is configured\nin us-east-1 and delivers straight\nto the raw bucket in London.",
       225, 560, 290, 60, fs=11, color=SUB, parent=edge)

acct = d.box("Account", 200, 740, 330, 260, parent=cloud)
oidc = d.res("CI role over OIDC\nread-only, this repo only", "identity_and_access_management", "security", 330, 800, parent=acct)
budget = d.res("Budget alarm, $10", "budgets", "cost", 330, 920, parent=acct, s=48, pos="right")

reg = d.group("eu-west-2 (London)", "region", 570, 140, 1030, 860, parent=cloud)
site = d.res("Site bucket (S3)\nstorefront, /insights/", "s3", "storage", 640, 180, parent=reg, pos="right")
api = d.res("Storefront API\n(Lambda function URL)", "lambda", "compute", 640, 320, parent=reg, pos="right")
raw = d.res("Raw logs (S3, KMS)\nfull IPs, deleted\nafter 7 days", "s3", "storage", 640, 500, parent=reg)

sched = d.res("EventBridge Scheduler\n05:00 UTC", "eventbridge", "integration", 900, 210, parent=reg)
sfn = d.res("Step Functions\none day at a time", "step_functions", "integration", 1100, 210, parent=reg, pos="above")
task = d.res("Pipeline task\n(Lambda)\nSQL, reconcile,\npublish", "lambda", "compute", 1330, 210, parent=reg, pos="right")

glue = d.res("Glue 5.0 Spark job\nparse, quarantine, mask IPs,\nkeyed-hash visitors, bot rules,\nData Quality rules",
             "glue", "analytics", 900, 500, parent=reg)
clean = d.res("Clean layer (S3, Iceberg)\nno raw IPs", "s3", "storage", 1100, 500, parent=reg)
athena = d.res("Athena\nown workgroup per role", "athena", "analytics", 1330, 500, parent=reg)
cur = d.res("Curated star schema and\nreport tables (S3, Iceberg)", "s3", "storage", 1330, 690, parent=reg)
lf = d.res("Lake Formation\nanalysts never see\nvisitor_id", "lake_formation", "analytics", 1100, 690, parent=reg)

kms = d.res("KMS key", "key_management_service", "security", 640, 860, parent=reg, s=48, pos="right")
ssm = d.res("HMAC key\n(Parameter Store)", "systems_manager", "management", 800, 860, parent=reg, s=48, pos="right")
alarm = d.res("Failure alarm\n(CloudWatch)", "cloudwatch_2", "management", 1236, 860, parent=reg, s=48)
sns = d.res("Alerts (SNS)", "sns", "integration", 1376, 860, parent=reg, s=48)
sqs = d.res("Alerts queue\n(SQS)", "sqs", "integration", 1506, 860, parent=reg, s=48)

d.edge(visitors, cf, "HTTPS")
d.edge(cf, site, "origin access control", nx=0, ny=0.5, via=[(600, 212)])
d.edge(cf, api, "origin access\ncontrol", ex=1, ey=0.75, nx=0, ny=0.5)
d.edge(cf, raw, "access logs", ex=1, ey=0.9, nx=0, ny=0.5, via=[(600, 268), (600, 532)])
d.edge(sched, sfn)
d.edge(sfn, task)
d.edge(sfn, glue, "runs the job", ex=0.25, ey=1, nx=0.5, ny=0, via=[(1116, 400), (932, 400)])
d.edge(raw, glue, "reads one day")
d.edge(glue, clean)
d.edge(clean, athena)
d.edge(task, athena, "SQL", ex=0.5, ey=1, nx=0.5, ny=0)
d.edge(athena, cur, ex=1, ey=0.85, nx=0.75, ny=0, via=[(1450, 554), (1450, 660), (1378, 660)])
d.edge(task, site, "data.json", ex=0.5, ey=0, nx=0.5, ny=0, via=[(1362, 160), (672, 160)], dashed=True)
d.edge(lf, cur, "column grants", dashed=True, color=GREY)
d.edge(analysts, athena, "queries", ex=0, ey=0.5, nx=1, ny=0.5, via=[(1560, 710), (1560, 532)], dashed=True, color=GREY)
d.edge(sfn, alarm, "any failure", ex=0.75, ey=1, nx=0.5, ny=0, color=RED, via=[(1148, 440), (1260, 440)], dashed=True)
d.edge(alarm, sns, color=RED)
d.edge(sns, sqs, color=RED)
d.edge(gh, oidc, "OIDC token", nx=0, ny=0.5)

d.text("Legend", 30, 1046, 200, 20, fs=13, bold=True)
d.text("Solid: data and requests.  Dashed grey: access.  Dashed red: failure path.  Dashed black: the pipeline publishes the dashboard data.",
       100, 1047, 1200, 20, fs=12, color=SUB)
# architecture.drawio is now edited directly in draw.io (AWS reference-architecture style), not generated here.

# =====================================================================
# 2. The daily pipeline (Step Functions)
# =====================================================================
p = Doc("Daily pipeline", 1560, 640)
p.add("", "rounded=0;fillColor=#FFFFFF;strokeColor=none;", 0, 0, 1560, 640)
p.text("The daily pipeline", 30, 20, 900, 34, fs=24, bold=True)
p.text("Step Functions, started at 05:00 UTC. Each day is replaced whole, so a re-run gives identical tables.",
       30, 56, 1300, 22, fs=14, color=SUB)

Y, H = 150, 170


def step(title, tech, desc, x, w=200, y=Y, h=H, **kw):
    return p.node(title, tech, desc, x, y, w, h, **kw)


resolve = step("Resolve", "Lambda", "Which days to process: yesterday, or a range for a backfill", 40, 180, h=80)
ensure = step("Ensure", "Lambda, Athena", "Create any missing tables", 40, 180, y=Y + 110, h=60)
p.boundary("Each day, one at a time (Map)", 260, 120, 1040, 250)
proc = step("Process", "Glue 5.0 Spark job",
            "Parse 33 fields. Quarantine bad lines with a reason. IP to /24 or /48, visitor = HMAC. "
            "Bot and device rules. Data Quality rules. Raw = clean + quarantined, or fail.", 285, 250)
fact = step("Load fact", "Lambda, Athena SQL", "Delete the day from fact_request, insert it again", 575, 210)
agg = step("Aggregate", "Lambda, Athena SQL", "Rebuild the day in 7 report tables: cost, edges, countries, cache, A/B, bots, errors",
           825, 210)
rec = step("Reconcile", "Lambda, Athena", "Clean rows = fact rows = report rows, or fail", 1075, 200)
pub = step("Publish", "Lambda", "Write insights/data.json, invalidate it in CloudFront", 1340, 190)
done = p.add("Done", f"ellipse;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={INK};fontColor={INK};fontSize=12;fontStyle=1;",
             1395, 400, 80, 40)
notify = step("Notify", "SNS (KMS)", "Execution name, error and cause, to the alerts topic", 580, 210, y=450, h=100, stroke=RED)
failed = p.add("Failed", f"ellipse;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={RED};fontColor={RED};fontSize=12;fontStyle=1;",
               860, 480, 80, 40)
p.edge(resolve, ensure)
p.edge(ensure, proc, ex=1, ey=0.5, nx=0, ny=0.8235)
for a_, b_ in [(proc, fact), (fact, agg), (agg, rec), (rec, pub)]:
    p.edge(a_, b_, ex=1, ey=0.5, nx=0, ny=0.5)
p.edge(pub, done)
p.line(685, 370, 685, 450, "any step fails, after retries", color=RED, dashed=True)
p.edge(notify, failed, color=RED)
p.text("Also on failure: a CloudWatch alarm on failed executions sends to the same topic, and an SQS queue keeps every alert. "
       "On a real failure during the build, the alert arrived 70 seconds after the run stopped (requirement: 15 minutes).",
       40, 590, 1480, 40, fs=12, color=SUB)
open(f"{OUTDIR}/pipeline-flow.drawio", "w").write(p.xml())

# =====================================================================
# 3. LinkedIn: 540x675 page, exported at 2x = 1080x1350
# =====================================================================
L = Doc("LinkedIn", 540, 675)
L.add("", "rounded=0;fillColor=#FFFFFF;strokeColor=none;", 0, 0, 540, 675)
L.text("Edge analytics on AWS", 22, 20, 500, 30, fs=22, bold=True)
L.text("CloudFront, Glue, Athena, Lake Formation, Step Functions, Terraform", 22, 52, 500, 20, fs=13, color=SUB)
S = 40
lcf = L.res("CloudFront\nA/B at the edge", "cloudfront", "analytics", 40, 100, s=S, fs=10)
lraw = L.res("Raw logs\n7 days", "s3", "storage", 150, 100, s=S, fs=10)
lglue = L.res("Glue\nmask IPs", "glue", "analytics", 260, 100, s=S, fs=10)
lath = L.res("Athena\nSQL reports", "athena", "analytics", 370, 100, s=S, fs=10)
ldash = L.res("Dashboard\nsame CDN", "s3", "storage", 470, 100, s=S, fs=10)
for a_, b_ in [(lcf, lraw), (lraw, lglue), (lglue, lath), (lath, ldash)]:
    L.edge(a_, b_)
L.text("Step Functions runs it daily. Lake Formation hides visitor ids from analysts.", 22, 186, 500, 20, fs=11, color=SUB)
L.text("What it answers", 22, 228, 500, 20, fs=13, bold=True)
for n, s_ in enumerate(["What the CDN costs by region, and what a cheaper price class saves",
                        "Where the site is slow: cache misses far from the London origin",
                        "Whether the homepage redesign sells more",
                        "How much of the traffic is bots",
                        "How to stop keeping visitors' IP addresses"]):
    L.text(s_, 22, 254 + n * 22, 500, 20, fs=12)
L.text("Measured", 22, 384, 500, 20, fs=13, bold=True)
for n, s_ in enumerate(["Campaign links: cache hits from 8% to 97.5% by stripping tracking parameters",
                        "Every planted answer found in 1.3 million synthetic log lines",
                        "No raw IP in 85 columns checked against 96,661 real addresses",
                        "Re-running a day: 11 of 11 tables identical",
                        "Failure alert in 70 seconds"]):
    L.text(s_, 22, 410 + n * 22, 500, 20, fs=12)
L.text("Everything in Terraform, with CI over OIDC and no stored AWS keys.", 22, 540, 500, 36, fs=12)
L.text("github.com/gumagatsby/aws-edge-analytics", 22, 646, 500, 18, fs=11, color=SUB)
open(f"{OUTDIR}/linkedin-architecture.drawio", "w").write(L.xml())
print("ok")
