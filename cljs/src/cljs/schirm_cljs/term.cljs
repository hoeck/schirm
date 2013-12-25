(ns schirm-cljs.term
  (:require [cljs.core.async :as async
             :refer [<! >! chan close! sliding-buffer put! alts!]]

            [schirm-cljs.screen-tests :as tests]

            [schirm-cljs.screen :as screen]
            [schirm-cljs.keys :as keys]
            [schirm-cljs.dom-utils :as dom-utils])

  (:require-macros [cljs.core.async.macros :as m :refer [go alt!]]))

;; events -> chan
;; socket-messages -> chan

(defn invoke-screen-method [state scrollback-screen alt-screen msg]
  (let [[meth & args] msg
        screen (if (:alt-mode state) alt-screen scrollback-screen)]
    ;; (.log js/console meth (clj->js args))
    (case meth
      "set-line-origin" (do (apply screen/set-origin screen args)
                            state)
      "reset"  (do (screen/reset scrollback-screen (nth args 0))
                   (screen/reset alt-screen (nth args 0))
                   state)
      "resize" (do (screen/set-size scrollback-screen (nth args 0))
                   (screen/set-size alt-screen (nth args 0))
                   state)
      "insert" (let [[line, col, string, attrs] args
                     style (apply screen/->CharacterStyle attrs)
                     ss (screen/StyledString. string style)]
                 (screen/update-line screen
                                     line
                                     #(screen/line-insert % ss col))
                 state)
      "insert-overwrite" (let [[line, col, string, attrs] args
                               style (apply screen/->CharacterStyle attrs)
                               ss (screen/StyledString. string style)]
                           (screen/update-line screen
                                               line
                                               #(screen/line-insert-overwrite % ss col))
                           state)
      "remove" (let [[line, col, n] args]
                 (screen/update-line screen
                                     line
                                     #(screen/line-remove % col n))
                 state)
      "insert-line" (do (screen/insert-line screen (screen/create-line []) (nth args 0))
                        state)
      "append-line" (do (screen/append-line screen (screen/create-line []))
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
                           (assoc state :alt-mode false)))))

(def chords {;; browsers have space and shift-space bound to scroll page down/up
             ["space"] (fn [send] (send {:string " "}) true)
             ["shift" "space"] (fn [send] (send {:string " "}) true)
             ;; ignore F12 as this opens the browsers devtools
             ["F12"] (fn [send] false)})

(defn setup-keys [send-chan]
  (let [send-key (fn [key]
                   (let [message {:name :keypress :key key}]
                     (put! send-chan (.stringify js/JSON (clj->js message)))))]
    (keys/setup-window-key-handlers js/window chords send-key)))

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

(defn setup-terminal []
  (let [ws-send  (chan)
        ws-recv (chan)
        ws-url (format "ws://%s" (-> js/window .-location .-host))
        container (dom-utils/select 'body)
        screens (setup-screens container ws-recv)]
    (setup-keys ws-send)
    (setup-resize container ws-send screens)
    (setup-websocket ws-url ws-send ws-recv)))

(defn init []
  (dom-utils/document-ready setup-terminal))

(defn tests []
  (dom-utils/document-ready (fn []
                              (doseq [result (tests/run-tests)]
                                (.log js/console (str result))))))

(init)
