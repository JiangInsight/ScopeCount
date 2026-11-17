args <- commandArgs(trailingOnly = TRUE)
src <- args[[1]]
dest <- args[[2]]
dir.create(dest, recursive = TRUE, showWarnings = FALSE)
d <- readRDS(src)
nraw <- nrow(d)
candidates <- c("date","subject_race","outcome","location","time","subject_sex",
                "citation_issued","subject_age","lat","lng","warning_issued",
                "arrest_made","search_conducted","violation","officer_id_hash",
                "contraband_found","search_basis","reason_for_stop","county_name","vehicle_make")
fields <- intersect(candidates, names(d))
stopifnot("type" %in% names(d), "date" %in% fields)
keep <- which(d$type == "vehicular")
masks <- integer(length(keep))
for (j in seq_along(fields)) {
  masks <- bitwOr(masks, bitwShiftL(as.integer(is.na(d[[fields[j]]][keep])), j-1L))
}
day <- as.integer(as.Date(d$date[keep]))
week <- (day + 3L) %/% 7L
hour <- if ("time" %in% fields) as.integer(as.numeric(d$time[keep], units="secs") %/% 3600) else rep(NA_integer_, length(keep))
stopifnot(all(hour[!is.na(hour)] >= 0L & hour[!is.na(hour)] < 24L))
writeBin(masks, file.path(dest, "masks.i32"), endian = "little")
writeBin(week, file.path(dest, "week.i32"), endian = "little")
writeBin(hour, file.path(dest, "hour.i32"), endian = "little")
writeLines(fields, file.path(dest, "fields.txt"))
writeLines(paste(nraw,length(keep)), file.path(dest, "sizes.txt"))
for (dim in strsplit(args[[3]], ",",fixed=TRUE)[[1]]) {
  key <- if (dim == "week") week else hour
  cond <- if (dim == "week") "date" else "time"
  valid <- !is.na(key)
  level <- sort(unique(key[valid]))
  bins <- match(key[valid], level)
  n <- tabulate(bins, nbins=length(level))
  missing <- numeric(length(level))
  cols <- setdiff(fields,cond)
  for (k in cols) {
    absent <- is.na(d[[k]][keep])[valid]
    missing <- missing + tabulate(bins[absent], nbins=length(level))
  }
  write.csv(data.frame(key=level,n=n,missing=missing), file.path(dest,paste0("oracle-",dim,".csv")), row.names=FALSE)
}
cat(basename(src),nraw,length(keep),length(fields),"\n")
