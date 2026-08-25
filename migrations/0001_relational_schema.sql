-- 0001_relational_schema
--
-- Everything the entity schemas cannot express.
--
-- DBAL builds each table from its entity definition, but its create-table
-- template emits columns only: the `foreign_key` and `indexes` an entity
-- declares are never created, and a column it no longer declares is never
-- dropped. So constraints, index changes and removals all have to live here.
--
-- Idempotent throughout, and safe to re-run: the runner records what it has
-- applied, but every statement is written so that re-running is harmless.

-- ── 1. componentTree outgrew its column ────────────────────────────────────
-- The live column was varchar(255) while the entity said `text`. Real trees
-- are thousands of characters, so every insert failed until this ran. Kept
-- for databases built before PageConfig.componentTree was removed entirely.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name = 'PageConfig' AND column_name = 'componentTree') THEN
    ALTER TABLE "PageConfig" ALTER COLUMN "componentTree" TYPE text;
  END IF;
END $$;

-- ── 2. Foreign keys ────────────────────────────────────────────────────────
-- Declared in the entity schemas, created by nobody. Each is dropped first so
-- the file can be re-run after a definition changes.

-- Page trees: a tree owns its nodes, a node owns its children and properties.
ALTER TABLE "PageTreeNode" DROP CONSTRAINT IF EXISTS "PageTreeNode_treeId_fkey";
ALTER TABLE "PageTreeNode" ADD CONSTRAINT "PageTreeNode_treeId_fkey"
  FOREIGN KEY ("treeId") REFERENCES "PageTree"(id) ON DELETE CASCADE;
ALTER TABLE "PageTreeNode" DROP CONSTRAINT IF EXISTS "PageTreeNode_parentId_fkey";
ALTER TABLE "PageTreeNode" ADD CONSTRAINT "PageTreeNode_parentId_fkey"
  FOREIGN KEY ("parentId") REFERENCES "PageTreeNode"(id) ON DELETE CASCADE;
ALTER TABLE "PageTreeProp" DROP CONSTRAINT IF EXISTS "PageTreeProp_nodeId_fkey";
ALTER TABLE "PageTreeProp" ADD CONSTRAINT "PageTreeProp_nodeId_fkey"
  FOREIGN KEY ("nodeId") REFERENCES "PageTreeNode"(id) ON DELETE CASCADE;
ALTER TABLE "PageTreeProp" DROP CONSTRAINT IF EXISTS "PageTreeProp_treeId_fkey";
ALTER TABLE "PageTreeProp" ADD CONSTRAINT "PageTreeProp_treeId_fkey"
  FOREIGN KEY ("treeId") REFERENCES "PageTree"(id) ON DELETE CASCADE;

-- A route points at a tree; losing the tree must not delete the route.
ALTER TABLE "PageConfig" DROP CONSTRAINT IF EXISTS "PageConfig_pageTreeId_fkey";
ALTER TABLE "PageConfig" ADD CONSTRAINT "PageConfig_pageTreeId_fkey"
  FOREIGN KEY ("pageTreeId") REFERENCES "PageTree"(id) ON DELETE SET NULL;

-- Workflow graphs.
ALTER TABLE "WorkflowNode" DROP CONSTRAINT IF EXISTS "WorkflowNode_workflowId_fkey";
ALTER TABLE "WorkflowNode" ADD CONSTRAINT "WorkflowNode_workflowId_fkey"
  FOREIGN KEY ("workflowId") REFERENCES "Workflow"(id) ON DELETE CASCADE;
ALTER TABLE "WorkflowNodeParam" DROP CONSTRAINT IF EXISTS "WorkflowNodeParam_nodeId_fkey";
ALTER TABLE "WorkflowNodeParam" ADD CONSTRAINT "WorkflowNodeParam_nodeId_fkey"
  FOREIGN KEY ("nodeId") REFERENCES "WorkflowNode"(id) ON DELETE CASCADE;
ALTER TABLE "WorkflowNodeParam" DROP CONSTRAINT IF EXISTS "WorkflowNodeParam_workflowId_fkey";
ALTER TABLE "WorkflowNodeParam" ADD CONSTRAINT "WorkflowNodeParam_workflowId_fkey"
  FOREIGN KEY ("workflowId") REFERENCES "Workflow"(id) ON DELETE CASCADE;
ALTER TABLE "WorkflowEdge" DROP CONSTRAINT IF EXISTS "WorkflowEdge_workflowId_fkey";
ALTER TABLE "WorkflowEdge" ADD CONSTRAINT "WorkflowEdge_workflowId_fkey"
  FOREIGN KEY ("workflowId") REFERENCES "Workflow"(id) ON DELETE CASCADE;
ALTER TABLE "WorkflowNodeCondition" DROP CONSTRAINT IF EXISTS "WNC_node_fkey";
ALTER TABLE "WorkflowNodeCondition" ADD CONSTRAINT "WNC_node_fkey"
  FOREIGN KEY ("nodeId") REFERENCES "WorkflowNode"(id) ON DELETE CASCADE;
ALTER TABLE "WorkflowNodeCondition" DROP CONSTRAINT IF EXISTS "WNC_wf_fkey";
ALTER TABLE "WorkflowNodeCondition" ADD CONSTRAINT "WNC_wf_fkey"
  FOREIGN KEY ("workflowId") REFERENCES "Workflow"(id) ON DELETE CASCADE;

-- The rest of the decomposed documents.
ALTER TABLE "SnippetParam" DROP CONSTRAINT IF EXISTS "SnippetParam_snippetId_fkey";
ALTER TABLE "SnippetParam" ADD CONSTRAINT "SnippetParam_snippetId_fkey"
  FOREIGN KEY ("snippetId") REFERENCES "Snippet"(id) ON DELETE CASCADE;
-- InstalledPackage's primary key is packageId; its id column is unused.
ALTER TABLE "InstalledPackageSetting" DROP CONSTRAINT IF EXISTS "IPS_pkg_fkey";
ALTER TABLE "InstalledPackageSetting" ADD CONSTRAINT "IPS_pkg_fkey"
  FOREIGN KEY ("installedPackageId") REFERENCES "InstalledPackage"("packageId") ON DELETE CASCADE;
ALTER TABLE "VideoTag" DROP CONSTRAINT IF EXISTS "VideoTag_videoId_fkey";
ALTER TABLE "VideoTag" ADD CONSTRAINT "VideoTag_videoId_fkey"
  FOREIGN KEY ("videoId") REFERENCES "Video"(id) ON DELETE CASCADE;
ALTER TABLE "StyleRule" DROP CONSTRAINT IF EXISTS "StyleRule_class_fkey";
ALTER TABLE "StyleRule" ADD CONSTRAINT "StyleRule_class_fkey"
  FOREIGN KEY ("styleClassId") REFERENCES "StyleClass"(id) ON DELETE CASCADE;
ALTER TABLE "StyleRuleProp" DROP CONSTRAINT IF EXISTS "StyleRuleProp_rule_fkey";
ALTER TABLE "StyleRuleProp" ADD CONSTRAINT "StyleRuleProp_rule_fkey"
  FOREIGN KEY ("ruleId") REFERENCES "StyleRule"(id) ON DELETE CASCADE;
ALTER TABLE "NotificationDatum" DROP CONSTRAINT IF EXISTS "NotifDatum_notif_fkey";
ALTER TABLE "NotificationDatum" ADD CONSTRAINT "NotifDatum_notif_fkey"
  FOREIGN KEY ("notificationId") REFERENCES "Notification"(id) ON DELETE CASCADE;
ALTER TABLE "AuditLogField" DROP CONSTRAINT IF EXISTS "AuditLogField_entry_fkey";
ALTER TABLE "AuditLogField" ADD CONSTRAINT "AuditLogField_entry_fkey"
  FOREIGN KEY ("auditLogId") REFERENCES "AuditLog"(id) ON DELETE CASCADE;

-- ── 3. Indexes ─────────────────────────────────────────────────────────────
-- DBAL creates indexes but never drops them, so a uniqueness rule outlives
-- the schema that declared it. These three had to widen to allow a repeated
-- name: a list-valued property is several rows sharing a name, ordered by
-- sortOrder.
DROP INDEX IF EXISTS "idx_pagetreeprop_nodeid_name";
DROP INDEX IF EXISTS "idx_pagetreeprop_node_name";
CREATE UNIQUE INDEX IF NOT EXISTS "idx_pagetreeprop_node_name_order"
  ON "PageTreeProp" ("nodeId", name, "sortOrder");
DROP INDEX IF EXISTS "idx_workflownodeparam_nodeid_name";
DROP INDEX IF EXISTS "idx_wfparam_node_name";
CREATE UNIQUE INDEX IF NOT EXISTS "idx_wfparam_node_name_order"
  ON "WorkflowNodeParam" ("nodeId", name, "sortOrder");
DROP INDEX IF EXISTS "idx_auditlogfield_auditlogid_kind_name";
CREATE UNIQUE INDEX IF NOT EXISTS "idx_auditlogfield_entry_kind_name_order"
  ON "AuditLogField" ("auditLogId", kind, name, "sortOrder");

CREATE INDEX IF NOT EXISTS "idx_pagetreenode_tree_parent_order"
  ON "PageTreeNode" ("treeId", "parentId", "sortOrder");
CREATE INDEX IF NOT EXISTS "idx_pagetreeprop_tree" ON "PageTreeProp" ("treeId");
CREATE UNIQUE INDEX IF NOT EXISTS "idx_wfnode_wf_key" ON "WorkflowNode" ("workflowId", "nodeKey");
CREATE INDEX IF NOT EXISTS "idx_wfedge_wf" ON "WorkflowEdge" ("workflowId");

-- ── 4. Columns the schemas no longer declare ───────────────────────────────
-- DBAL adds columns but never removes them, so a document column outlives its
-- definition. Every one of these has either been decomposed into its own table
-- or was empty in every row.
ALTER TABLE "PageConfig"       DROP COLUMN IF EXISTS "componentTree";
ALTER TABLE "Workflow"         DROP COLUMN IF EXISTS "nodes";
ALTER TABLE "Workflow"         DROP COLUMN IF EXISTS "edges";
ALTER TABLE "Workflow"         DROP COLUMN IF EXISTS "executionConfig";
ALTER TABLE "Workflow"         DROP COLUMN IF EXISTS "metadata";
ALTER TABLE "Snippet"          DROP COLUMN IF EXISTS "inputParameters";
ALTER TABLE "InstalledPackage" DROP COLUMN IF EXISTS "config";
ALTER TABLE "Video"            DROP COLUMN IF EXISTS "tags";
ALTER TABLE "StyleClass"       DROP COLUMN IF EXISTS "classes";
ALTER TABLE "Notification"     DROP COLUMN IF EXISTS "data";
ALTER TABLE "AuditLog"         DROP COLUMN IF EXISTS "details";
ALTER TABLE "AuditLog"         DROP COLUMN IF EXISTS "oldValue";
ALTER TABLE "AuditLog"         DROP COLUMN IF EXISTS "newValue";

-- Empty in every row and no longer declared. When these features are built
-- they get tables, like everything else.
ALTER TABLE "ComponentTree"  DROP COLUMN IF EXISTS "rootNode";
ALTER TABLE "ComponentTree"  DROP COLUMN IF EXISTS "tags";
ALTER TABLE "EmailMessage"   DROP COLUMN IF EXISTS "bcc";
ALTER TABLE "EmailMessage"   DROP COLUMN IF EXISTS "cc";
ALTER TABLE "EmailMessage"   DROP COLUMN IF EXISTS "headers";
ALTER TABLE "EmailMessage"   DROP COLUMN IF EXISTS "labels";
ALTER TABLE "EmailMessage"   DROP COLUMN IF EXISTS "to";
ALTER TABLE "IRCMembership"  DROP COLUMN IF EXISTS "metadata";
ALTER TABLE "IRCMessage"     DROP COLUMN IF EXISTS "metadata";
ALTER TABLE "MediaAsset"     DROP COLUMN IF EXISTS "metadata";
ALTER TABLE "MediaJob"       DROP COLUMN IF EXISTS "params";
ALTER TABLE "ProjectModel"   DROP COLUMN IF EXISTS "fields";
ALTER TABLE "StreamChannel"  DROP COLUMN IF EXISTS "metadata";
ALTER TABLE "StreamScene"    DROP COLUMN IF EXISTS "layout";
ALTER TABLE "StreamScene"    DROP COLUMN IF EXISTS "sources";
ALTER TABLE "StreamScene"    DROP COLUMN IF EXISTS "transitions";
ALTER TABLE "StreamSchedule" DROP COLUMN IF EXISTS "metadata";
ALTER TABLE "StreamSchedule" DROP COLUMN IF EXISTS "recurrence";
ALTER TABLE "Theme"          DROP COLUMN IF EXISTS "colors";
ALTER TABLE "Theme"          DROP COLUMN IF EXISTS "spacing";
ALTER TABLE "Theme"          DROP COLUMN IF EXISTS "typography";

-- A key/value store still needs a value; it just does not need a document.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name = 'KVEntry' AND column_name = 'value'
               AND data_type IN ('json', 'jsonb')) THEN
    ALTER TABLE "KVEntry" ALTER COLUMN "value" TYPE text USING "value"::text;
  END IF;
END $$;

-- The v1 ComponentNode belongs to CodeForge. An earlier pass reshaped it by
-- mistake; this restores what its entity declares.
ALTER TABLE "ComponentNode" ADD COLUMN IF NOT EXISTS "childIds" character varying;
ALTER TABLE "ComponentNode" ADD COLUMN IF NOT EXISTS "order" integer;
ALTER TABLE "ComponentNode" ADD COLUMN IF NOT EXISTS "pageId" character varying;
