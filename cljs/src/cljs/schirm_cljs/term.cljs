(ns schirm-cljs.term
  (:require [cljs.core.async :as async
             :refer [<! >! chan close! sliding-buffer put! alts!]]

            [clojure.string :as string]

            [clojure.browser.repl :as repl]

            [schirm-cljs.screen-tests :as tests]

            [schirm-cljs.screen :as screen]
            [schirm-cljs.keys :as keys]
            [schirm-cljs.dom-utils :as dom-utils]
            [schirm-cljs.word-select :as word-select]
            [schirm-cljs.copy-n-paste-hack :as copy-n-paste-hack])

  (:require-macros [cljs.core.async.macros :as m :refer [go alt!]]))

;; events -> chan
;; socket-messages -> chan

(defn create-styled-string [string attrs]
  (screen/StyledString. string (apply screen/->CharacterStyle attrs)))

(defn create-fragment-from-lines
  "Create a document fragment from a seq of seqs of raw segments.

  Raw segments are tuples of (string, class-string) forming the basic
  parts of a line."
  [lines]
  (let [fragment (.createDocumentFragment js/document)]
    (doseq [raw-segments lines]
      (let [line (.createElement js/document "div")]
        (doseq [[string class] (if (empty? raw-segments)
                                 [[" " ""]] ;; empty line
                                 raw-segments)]
          (let [segment (.createElement js/document "span")]
            (set! (.-className segment) class)
            (set! (.-textContent segment) string)
            (.appendChild line segment)))
        (.appendChild fragment line)))
    fragment))

(defn create-iframe [id]
  (let [scroll-size (dom-utils/scrollbar-size)
        uri (format "http://%s.localhost" id)]
    (dom-utils/create-element
     "iframe"
     {:style {:width "100%",
              :min-height (:vertical scroll-size)
              :height (:vertical scroll-size)}
      :src uri
      :id id})))

(def iframe-menu-thumb-svg "<svg class=\"iframe-menu-thumb\">
  <g transform=\"scale(2) translate(-23.625,-584.43734)\">
    <path
       d=\"m 25.643378,584.49888 -1.966539,1.96766 2.976292,2.97629 -3.028131,3.02814 1.967666,1.96653 3.027003,-3.02701 2.925578,2.92446 1.967666,-1.96767 -2.925578,-2.92445 2.873738,-2.87373 -1.967665,-1.96655 -2.872612,2.87262 z\"/>
  </g>
</svg>")

(defn invoke-screen-method [state scrollback-screen alt-screen msg]
  (let [[meth & args] msg
        screen (if (:alt-mode state) alt-screen scrollback-screen)]
    (case meth
      "set-line-origin" (do (apply screen/set-origin screen args)
                            state)
      "reset"  (do (screen/reset scrollback-screen (nth args 0))
                   (screen/reset alt-screen (nth args 0))
                   state)
      "resize" (do (screen/set-size scrollback-screen (nth args 0) (nth args 1))
                   (screen/set-size alt-screen (nth args 0) (nth args 1))
                   state)
      "insert" (let [[line, col, string, attrs] args
                     ss (create-styled-string string attrs)]
                 (screen/update-line screen
                                     line
                                     #(screen/line-insert % ss col))
                 state)
      "insert-overwrite" (let [[line, col, string, attrs] args
                               ss (create-styled-string string attrs)]
                           (screen/update-line screen
                                               line
                                               #(screen/line-insert-overwrite % ss col))
                           state)
      "remove" (let [[line, col, n] args]
                 (screen/update-line screen
                                     line
                                     #(screen/line-remove % col n))
                 state)
      "insert-line" (do (screen/insert-line screen (screen/create-line [(screen/default-styled-string 1)]) (nth args 0))
                        state)
      "append-line" (do (screen/append-line screen (screen/create-line [(screen/default-styled-string 1)]))
                        state)
      "append-many-lines" (let [lines (nth args 0 [])]
                            (screen/append-line screen (create-fragment-from-lines lines))
                            state)
      "remove-line" (do (screen/remove-line screen (nth args 0))
                        state)
      "adjust" (do (screen/adjust screen)
                   state)
      "cursor" (let [[line, col] args]
                 (screen/set-cursor screen line col)
                 state)
      "enter-alt-mode" (do (screen/show scrollback-screen false)
                           (screen/show alt-screen true)
                           (assoc state :alt-mode true))
      "leave-alt-mode" (do (screen/show scrollback-screen true)
                           (screen/show alt-screen false)
                           (screen/reset alt-screen)
                           (assoc state :alt-mode false))

      "scrollback-cleanup" (do (screen/scrollback-cleanup screen (nth args 0))
                               state)
      "set-title" (do (set! (.-title js/document) (nth args 0))
                      state)

      ;; iframe
      "iframe-enter" (let [[iframe-id pos] args
                           menu-thumb (dom-utils/create-element-from-string iframe-menu-thumb-svg)
                           iframe (create-iframe iframe-id)]
                       (screen/update-line screen pos
                                           (fn [l]
                                             (set! (.-innerHTML l) "")
                                             ;; make the line position:relative so the close div
                                             ;; appears on the upper left over the iframe
                                             (-> l .-classList (.add "iframe-line"))
                                             (.appendChild l menu-thumb)
                                             (.appendChild l iframe)
                                             (.focus iframe)))
                       (.addEventListener iframe "webkitTransitionEnd" #(screen/auto-scroll screen))
                       state)

      "iframe-resize" (let [[iframe-id height] args
                            iframe (.getElementById js/document iframe-id)
                            height-style (if (==  height "fullscreen") "100%" (format "%spx" height))]
                        (when iframe (-> iframe .-style .-height (set! height-style)))
                        (.setTimeout js/window #(screen/auto-scroll screen))
                        state)

      "iframe-set-url" (let [[iframe-id url] args
                             iframe (.getElementById js/document iframe-id)]
                         (set! (.-src iframe) url)
                         state)

      ;; debug
      "start-clojurescript-repl" (do (repl/connect "http://localhost:9000/repl")
                                     state)
      )))

(def chords {;; paste xselection
             [:shift :insert]
             (fn [{:keys [send]}]
               ;; paste the primary x selection using `xsel`
               (send {:name "paste_selection"}))
             [:control :v]
             (fn [{:keys [send]}] (copy-n-paste-hack/key-paste #(send {:name "paste_selection" :string %})))
             ;; scrolling
             [:shift :page_up]   (fn [env] (screen/scroll :page-up)   true)
             [:shift :page_down] (fn [env] (screen/scroll :page-down) true)
             [:shift :home] (fn [env] (screen/scroll :top)    true)
             [:shift :end]  (fn [env] (screen/scroll :bottom) true)
             ;; browsers have space and shift-space bound to scroll page down/up
             [:space] (fn [{:keys [send-key]}] (send-key {:string " "}) true)
             [:shift :space] (fn [{:keys [send-key]}] (send-key {:string " "}) true)
             ;; ignore F12 as this opens the browsers devtools
             [:F12] (fn [env] false)})

(defn setup-keys [send-chan send-callback]
  (let [send (fn [message] (put! send-chan (.stringify js/JSON (clj->js message))))
        send-key (fn [key]
                   (when send-callback (send-callback))
                   (let [message {:name :keypress :key key}]
                     (send message)))
        ;; an environment to implement key-chord actions
        env {:send-key send-key
             :send send}]
    (keys/setup-window-key-handlers js/window chords env)))

(defn setup-screens [parent-element input-chan]
  (let [[scrollback-screen alt-screen :as screens] (screen/create-screens parent-element)
        state (atom {})]
    (screen/show alt-screen false)
    (go
     (loop []
       (doseq [message (<! input-chan)]
         (reset! state (invoke-screen-method @state scrollback-screen alt-screen message)))
       (recur)))
    screens))

(defn setup-resize [container ws-send screens]
  (let [resize-screen (fn [] (let [pre (.-element (first (filter #(.-visible %) screens)))
                                   new-size (screen/container-size container pre)
                                   message (clj->js (assoc new-size :name :resize))]
                               (put! ws-send (.stringify js/JSON message))))]
    (set! (.-onresize js/window) resize-screen)
    (resize-screen)))

(defn setup-word-select [screens]
  (doseq [s screens]
    (.addEventListener (.-element s)
                       "dblclick"
                       #(word-select/select-word % s))))

(defn setup-iframe-focus []
  (.addEventListener js/window "focus" (fn []
                                         (when-let [e (-> js/document (.querySelector "iframe.focus"))]
                                           (-> e .-classList (.remove "focus")))))
  (.addEventListener js/window "blur" (fn []
                                        (.setTimeout js/window (fn []
                                                                 (when (-> js/document .-activeElement .-tagName (= "IFRAME"))
                                                                   (-> js/document .-activeElement .-classList (.add "focus"))))
                                                     0))))

(defn setup-websocket [url in out]
  (let [ws (js/WebSocket. url)]
    (set! (.-onmessage ws)
          (fn [ev]
            (if (not= "" (.-data ev))
              (put! out (.parse js/JSON (.-data ev))))))
    (set! (.-onopen ws)
          #(go
            (loop []
              (let [msg (<! in)]
                (.send ws msg)
                (recur)))))))

(defn setup-right-click
  "Use a nearly invisible pixel-size textarea to be able to paste text."
  [container ws-send]
  (copy-n-paste-hack/setup-mouse-paste
   container
   #(put! ws-send (.stringify js/JSON (clj->js {:name "paste_selection" :string %})))))

(defn setup-iframe-menu-thumb
  "The iframe-menu-thumb provides control over applications running in frame mode.

  Analogous to control flow keyboard shortcuts, it is able to 'close'
  the iframe (making the app to leave frame mode) or to 'kill' the app
  by sending SIGINT (CTRL-C)."
  [ws-send screens]
  (let [a 1]
    (doseq [s screens]
      (.addEventListener (.-element s)
                         "click"
                         (fn [e]
                           (let [target (-> e .-target)
                                 line? #(and (-> % .-classList)
                                             (-> % .-classList (.contains "iframe-line")))]
                             ;; TODO: after qtwebkit update, check whether svg elements support .-classList!
                             (when (and (or (-> target .-tagName (== "svg"))
                                            (-> target .-tagName (== "path")))
                                        (or (-> target .-parentElement line?)
                                            (-> target .-parentElement .-parentElement line?)
                                            (-> target .-parentElement .-parentElement .-parentElement line?)))
                               (let [message (clj->js {:name "iframe_request_close"})]
                                 (put! ws-send (.stringify js/JSON message))))))))))

(defn setup-terminal []
  (let [ws-send  (chan)
        ws-recv (chan)
        ws-url (format "ws://%s" (-> js/window .-location .-host))
        container (dom-utils/select 'body)
        screens (setup-screens container ws-recv)]
    (setup-keys ws-send
                ;; enable auto-scroll when typing non-chord keys
                ;; == sending keystrokes to the terminal
                #(screen/auto-scroll (nth screens 0) true))
    (setup-word-select screens)
    (setup-iframe-focus)
    (setup-iframe-menu-thumb ws-send screens)
    (setup-right-click container ws-send)
    (setup-resize container ws-send screens)
    (setup-websocket ws-url ws-send ws-recv)))

(defn init []
  (dom-utils/document-ready setup-terminal))

(defn tests []
  (dom-utils/document-ready (fn []
                              (doseq [result (tests/run-tests)]
                                (.log js/console (str result))))))

(init)
