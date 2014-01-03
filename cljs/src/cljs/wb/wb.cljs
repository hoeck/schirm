(ns wb.wb ;; workbench
  (:use [schirm-cljs.dom-utils :only [select]])
  (:require [clojure.string :as string]

            [cljs.core.async :as async
             :refer [<! >! chan close! sliding-buffer put! alts!]]

            [schirm-cljs.screen :as screen]
            [schirm-cljs.screen-tests :as screen-tests]
            [schirm-cljs.dom-utils :as dom-utils])

  (:require-macros [cljs.core.async.macros :as m :refer [go alt!]]))

(defn reload []
  (let [delay-in-ms 100]
    (js/setTimeout (fn [] (-> js/window .-location .reload)) delay-in-ms)
    (symbol (format "reloading-in-%s-milliseconds" delay-in-ms))))
