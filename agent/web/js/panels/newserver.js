/* The New server flow in the "+" tab: which edition, which kind of server,
   which Minecraft version, then its name, color and memory, and Minecraft's
   own rules.

   Bedrock skips the comparison table (there is one kind of Bedrock server)
   and goes straight to the version, name, color and Mojang's EULA and
   Privacy Policy. It has no memory setting.

   The comparison table is built from what each type says about itself
   (/api/server-types), so it cannot drift from what the app actually does.
   It describes; it never claims a number nobody measured. */

import { api } from "../api.js";
import { loadServers, selectServer } from "../servers.js";
import { state } from "../state.js";
import { t, technical } from "../strings.js";
import { advanced, busy, card, el, fmt, icon, known, problem, toast } from "../ui.js";

/* Add-ons: what this type takes, in the words the type uses for them. */
function contentCell(type) {
  if (!type.content) return t("new.content_none");
  return t(type.content === "plugins" ? "new.content_plugins" : "new.content_mods");
}

const yesNo = (value) => (value ? t("value.yes") : t("value.no"));

/* One table, or a stack of cards on a phone, from the capabilities. The
   same rows either way: the CSS folds the table into cards. */
function comparison(types, recommended, onChoose) {
  const columns = [
    [t("new.col_kind"), (type) => el("div", { class: "type-name" },
      el("strong", {}, type.name),
      type.id === recommended ? el("span", { class: "tag rec-tag" }, t("new.recommended")) : null)],
    [t("new.col_best_for"), (type) => t(`types.${type.id}.best`)],
    [t("new.col_content"), contentCell],
    [t("new.col_modrinth"), (type) => yesNo(type.modrinth)],
    [t("new.col_crossplay"), (type) => yesNo(type.crossplay)],
    [t("new.col_ease"), (type) => t(`new.ease_${type.ease}`)],
  ];
  if (technical()) {
    columns.push(
      [t("new.col_loader"), (type) => type.loader_name || t("new.content_none")],
      [t("new.col_metadata"), (type) => (type.metadata_files || []).join(", ") || "—"],
      [t("new.col_source"), (type) => type.version_source]);
  }
  columns.push([t("new.col_choose"), (type) => el("button", {
    class: "btn small", type: "button", "data-type": type.id,
    onclick: () => onChoose(type),
  }, t("new.choose"))]);

  return el("div", { class: "table-wrap" },
    el("table", { class: "type-table" },
      el("thead", {}, el("tr", {}, columns.map(([label]) => el("th", {}, label)))),
      el("tbody", {}, types.map((type) => el("tr", { class: type.id === recommended ? "is-rec" : null },
        columns.map(([label, cell]) => el("td", { "data-label": label }, cell(type))))))));
}

/* The version picker for the chosen type. Latest stable is selected; the
   in-between versions (snapshots) are behind a switch, because they are
   not meant for a server people play on. */
function versionPicker(payload, onPick) {
  const stable = payload.versions.filter((v) => v.stable);
  const select = el("select", { id: "new-version", class: "grow-input" });
  const loader = el("select", { id: "new-loader" });
  const snapshots = el("input", { type: "checkbox", id: "new-snapshots" });

  const fill = () => {
    const list = snapshots.checked ? payload.versions : stable;
    select.replaceChildren(...list.map((v) => el("option", {
      value: v.minecraft,
      selected: v.minecraft === payload.latest_stable ? "selected" : false,
    }, v.stable ? v.minecraft : t("new.snapshot_option", { version: v.minecraft }))));
    pick();
  };
  const pick = () => {
    const entry = payload.versions.find((v) => v.minecraft === select.value);
    const loaders = (entry && entry.loaders) || [];
    loader.replaceChildren(...loaders.map((v, index) => el("option",
      { value: v, selected: index === 0 ? "selected" : false }, v)));
    onPick(select.value, loaders[0] || null, entry);
  };
  select.addEventListener("change", pick);
  snapshots.addEventListener("change", fill);
  loader.addEventListener("change", () => onPick(select.value, loader.value,
    payload.versions.find((v) => v.minecraft === select.value)));
  fill();

  return el("div", { class: "stack" },
    el("div", { class: "field" },
      el("label", { for: "new-version" }, t("new.version")),
      select,
      el("div", { class: "hint" }, t("new.version_hint", { source: payload.source }))),
    payload.snapshots
      ? el("label", { class: "switch" }, snapshots, el("span", {}, t("new.show_snapshots")))
      : null,
    payload.picks_loader && loader.children.length
      ? advanced(t("new.loader_choice"),
          el("div", { class: "field" },
            el("label", { for: "new-loader" },
              t("new.loader_version", { loader: payload.loader_name || "" })),
            loader,
            el("div", { class: "hint" }, t("new.loader_hint"))))
      : null);
}

export function newServerPanel() {
  const wrap = el("div", { class: "stack new-server" });
  const chosen = { type: null, minecraft: null, loader: null, color: state.nextColor };
  let options = null;

  const typeBox = el("div", {});
  const versionBox = el("div", {});
  const detailBox = el("div", {});

  const name = el("input", { id: "new-name", maxlength: "60", autocomplete: "off" });
  const folder = el("input", {
    id: "new-folder", maxlength: "400", class: "mono", autocomplete: "off",
    placeholder: "C:\\Minecraft\\Survival",
  });
  const memory = el("input", { id: "new-memory", type: "number", min: "1024", max: "65536", step: "512" });
  const eula = el("input", { type: "checkbox", id: "new-eula" });

  function swatches() {
    const used = new Set(state.servers.map((s) => s.color));
    return el("div", { class: "swatches", role: "radiogroup", "aria-label": t("serverset.color") },
      state.palette.map((p) => {
        const label = el("label", { class: "swatch-choice", title: t(`color.${p.id}`) },
          el("input", {
            type: "radio", name: "new-server-color", value: p.hex,
            checked: p.hex === chosen.color ? "checked" : false,
            "aria-label": used.has(p.hex) ? t("add.color_used", { color: t(`color.${p.id}`) }) : t(`color.${p.id}`),
            onchange: () => { chosen.color = p.hex; },
          }),
          el("span", { class: `swatch${used.has(p.hex) ? " used" : ""}`, "aria-hidden": "true" }));
        label.style.setProperty("--swatch", p.hex);
        return label;
      }));
  }

  /* Steps 3 and 4 appear once a type is chosen, so the page is one thing
     at a time rather than a wall of fields. */
  const isBedrock = () => Boolean(chosen.type && chosen.type.edition === "bedrock");

  async function chooseType(type) {
    chosen.type = type;
    chosen.minecraft = null;
    typeBox.querySelectorAll("button[data-type]").forEach((button) => {
      const picked = button.dataset.type === type.id;
      button.classList.toggle("primary", picked);
      button.textContent = picked ? t("new.chosen") : t("new.choose");
    });
    versionBox.replaceChildren(el("div", { class: "empty", "aria-busy": "true" }, t("status.loading")));
    detailBox.replaceChildren();
    let payload;
    try {
      payload = await api(`/server-types/${type.id}/versions`);
    } catch (err) {
      versionBox.replaceChildren(card(t("new.step_version"), problem(err.message)));
      return;
    }
    const javaBox = el("div", {});
    versionBox.replaceChildren(card(t("new.step_version"),
      payload.latest_only ? el("p", { class: "hint mt-0" }, t("new.bedrock_versions")) : null,
      payload.source_problem ? problem(payload.source_problem) : null,
      versionPicker(payload, (minecraft, loader, entry) => {
        chosen.minecraft = minecraft;
        chosen.loader = loader;
        javaBox.replaceChildren(...[javaTooOld(entry)].filter(Boolean));
      }), javaBox));
    detailBox.replaceChildren(detailStep(type));
    versionBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  /* Java on this PC is older than the chosen version needs: said before
     anything is created, with where to get a newer one. */
  function javaTooOld(entry) {
    const have = options.java && options.java.version_major;
    const need = entry && entry.java_required;
    if (!known(have) || !known(need) || have >= need) return null;
    return el("div", { class: "banner warn mt-12" }, el("div", { class: "grow" },
      t("new.java_old", { version: entry.minecraft, need, have }),
      el("p", { class: "mt-0" },
        el("a", { href: options.java_download, target: "_blank", rel: "noopener noreferrer" },
          t("new.java_get")))));
  }

  /* Bedrock: Mojang's EULA and Privacy Policy, one tick for both. Nothing
     is downloaded until it is ticked. */
  function bedrockRules() {
    const terms = options.bedrock || {};
    const link = (href, text) => el("a", { href, target: "_blank", rel: "noopener noreferrer" },
      text, icon("chevron"));
    return card(t("new.step_rules"),
      el("p", { class: "hint mt-0" }, t("new.bedrock_terms_intro")),
      el("p", { class: "mt-0 link-row" },
        link(terms.eula_url, t("new.eula_link")),
        link(terms.privacy_url, t("new.privacy_link"))),
      el("label", { class: "switch" }, eula, el("span", {}, t("new.bedrock_tick"))),
      el("div", { class: "btn-row mt-12" },
        el("button", { class: "btn primary", type: "button", id: "new-create" }, t("new.create")),
        el("span", { class: "hint" }, t("new.create_hint"))));
  }

  function bedrockDetails() {
    const port = options.bedrock && options.bedrock.port;
    return el("div", { class: "stack" },
      card(t("new.step_details"),
        el("div", { class: "grid cols-2" },
          el("div", { class: "field" }, el("label", { for: "new-name" }, t("add.name")), name),
          el("div", { class: "field" },
            el("label", { for: "new-folder" }, t("new.folder")), folder,
            el("div", { class: "hint" }, t("new.folder_hint")))),
        el("div", { class: "field" }, el("span", { class: "field-label" }, t("serverset.color")), swatches()),
        el("div", { class: "hint" }, known(port)
          ? t("new.bedrock_port_hint", { port })
          : t("new.bedrock_no_port"))),
      bedrockRules());
  }

  function detailStep(type) {
    if (type.edition === "bedrock") return bedrockDetails();
    memory.value = options.memory_mb;
    const javaProblem = options.java && !known(options.java.version_major);
    return el("div", { class: "stack" },
      card(t("new.step_details"),
        el("div", { class: "grid cols-2" },
          el("div", { class: "field" }, el("label", { for: "new-name" }, t("add.name")), name),
          el("div", { class: "field" },
            el("label", { for: "new-folder" }, t("new.folder")), folder,
            el("div", { class: "hint" }, t("new.folder_hint")))),
        el("div", { class: "field" }, el("span", { class: "field-label" }, t("serverset.color")), swatches()),
        advanced(t("add.more_options"),
          el("div", { class: "field" },
            el("label", { for: "new-memory" }, t("new.memory")), memory,
            el("div", { class: "hint" }, options.memory_reason)),
          el("div", { class: "hint" }, t("new.port_hint", { port: options.port })))),
      card(t("new.step_rules"),
        el("p", { class: "hint mt-0" }, t("new.eula_intro")),
        el("p", { class: "mt-0" },
          el("a", { href: options.eula_url, target: "_blank", rel: "noopener noreferrer" },
            t("new.eula_link"), icon("chevron"))),
        el("label", { class: "switch" }, eula, el("span", {}, t("new.eula_tick"))),
        javaProblem
          ? el("div", { class: "banner warn mt-12" },
              el("div", { class: "grow" }, t("new.java_unknown"),
                el("p", { class: "mt-0" },
                  el("a", { href: options.java_download, target: "_blank", rel: "noopener noreferrer" },
                    t("new.java_get")))))
          : null,
        el("div", { class: "btn-row mt-12" },
          el("button", { class: "btn primary", type: "button", id: "new-create" }, t("new.create")),
          el("span", { class: "hint" }, t("new.create_hint")))));
  }

  async function create(button) {
    if (!chosen.type || !chosen.minecraft) { toast(t("new.need_version"), "warn"); return; }
    if (!name.value.trim() || !folder.value.trim()) {
      toast(t("add.need_name_and_folder"), "warn");
      (name.value.trim() ? folder : name).focus();
      return;
    }
    if (!eula.checked) {
      toast(t(isBedrock() ? "new.need_bedrock_terms" : "new.need_eula"), "warn");
      eula.focus();
      return;
    }
    await busy(button, t("new.creating"), async () => {
      try {
        const result = await api("/new-server", {
          method: "POST",
          body: {
            name: name.value.trim(),
            directory: folder.value.trim(),
            type: chosen.type.id,
            minecraft_version: chosen.minecraft,
            loader_version: chosen.loader,
            memory_mb: isBedrock() ? null : Number(memory.value) || null,
            color: chosen.color,
            eula_accepted: true,
          },
        });
        toast(t("new.created", { name: result.name }), "success", 9000);
        if (result.verified === false) toast(t("new.unverified"), "warn", 12000);
        await loadServers();
        await selectServer(result.server_id, "dashboard");
      } catch (err) {
        toast(err.message, "error", 12000);
      }
    });
  }

  wrap.addEventListener("click", (event) => {
    const button = event.target.closest("#new-create");
    if (button) create(button);
  });

  (async () => {
    try {
      options = await api("/new-server/options");
    } catch (err) {
      wrap.replaceChildren(problem(err.message));
      return;
    }
    const edition = el("div", { class: "choices editions", role: "radiogroup", "aria-label": t("new.edition") },
      el("label", { class: "choice" },
        el("input", { type: "radio", name: "new-edition", value: "java", checked: "checked" }),
        el("span", { class: "choice-text" },
          el("strong", {}, t("new.java")),
          el("span", { class: "hint" }, t("new.java_hint")))),
      el("label", { class: "choice" },
        el("input", { type: "radio", name: "new-edition", value: "bedrock" }),
        el("span", { class: "choice-text" },
          el("strong", {}, t("new.bedrock")),
          el("span", { class: "hint" }, t("new.bedrock_hint")))));

    // The table compares the Java kinds; Bedrock has one kind of server,
    // so choosing Bedrock skips it.
    const javaTypes = options.types.filter((type) => type.edition !== "bedrock");
    const bedrockType = options.types.find((type) => type.edition === "bedrock");
    edition.addEventListener("change", (event) => {
      if (event.target.name !== "new-edition") return;
      const bedrock = event.target.value === "bedrock";
      typeBox.hidden = bedrock;
      if (bedrock && bedrockType) {
        chooseType(bedrockType);
      } else {
        chosen.type = null;
        chosen.minecraft = null;
        versionBox.replaceChildren();
        detailBox.replaceChildren();
        typeBox.querySelectorAll("button[data-type]").forEach((button) => {
          button.classList.remove("primary");
          button.textContent = t("new.choose");
        });
      }
    });

    typeBox.replaceChildren(card(t("new.step_kind"),
      el("p", { class: "hint mt-0" }, t("new.kind_hint")),
      comparison(javaTypes, options.recommended, chooseType),
      el("p", { class: "hint" },
        t("new.rec_why", { name: (options.types.find((x) => x.id === options.recommended) || {}).name || "" }))));

    wrap.replaceChildren(
      card(t("new.step_edition"), edition),
      typeBox, versionBox, detailBox);
    // Nothing is chosen for the person, and no version list is fetched
    // until they pick a kind: the table is the choice.
  })();

  // Memory is shown in the person's own words next to the box.
  memory.addEventListener("change", () => {
    const shown = fmt.memory(Number(memory.value));
    if (shown) memory.title = shown;
  });

  return wrap;
}
